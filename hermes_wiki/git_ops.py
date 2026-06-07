"""Per-wiki git repository operations.

Each LLM Wiki owns an independent git repository rooted at
``<home>/wikis/<slug>/``. The repository tracks durable wiki artifacts while
projection binaries remain local, rebuildable support files.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

GITIGNORE_MARKER = "# Hermes Wiki projection binaries"
GITIGNORE_ENTRIES = (
    "wiki.db",
    "wiki.db-shm",
    "wiki.db-wal",
    "wiki.db.tmp",
    "wiki.db.tmp-shm",
    "wiki.db.tmp-wal",
    "wiki.db.tmp.lock",
    ".ingest.lock",
    "db_versions/*.db",
    "!db_versions/manifest.jsonl",
    "raw/large/",
)
_EMAIL_SAFE_RE = re.compile(r"[^A-Za-z0-9._%+-]+")


class GitOpsError(RuntimeError):
    """Raised when a git operation fails."""


@dataclass(frozen=True, slots=True)
class GitCommitResult:
    """Result of attempting to create an attributed wiki commit."""

    repo_path: Path
    message: str
    committed: bool
    commit_id: str | None
    staged_files: tuple[str, ...]


def initialize_wiki_repo(home: Path | str, slug: str) -> Path:
    """Initialize and return the per-wiki git repo at ``<home>/wikis/<slug>/``."""

    clean_slug = _validate_slug(slug)
    wiki_root = Path(home) / "wikis" / clean_slug
    wiki_root.mkdir(parents=True, exist_ok=True)
    if not (wiki_root / ".git").exists():
        _git_init(wiki_root)
    ensure_gitignore(wiki_root)
    return wiki_root


def ensure_gitignore(wiki_root: Path | str) -> Path:
    """Ensure projection binaries are ignored while ``manifest.jsonl`` stays trackable."""

    root = Path(wiki_root)
    root.mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    updated = existing.splitlines()
    if GITIGNORE_MARKER not in updated:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append(GITIGNORE_MARKER)
    for entry in GITIGNORE_ENTRIES:
        if entry not in updated:
            updated.append(entry)
    gitignore.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
    return gitignore


def format_commit_message(*, action: str, what: str, author: str) -> str:
    """Format the canonical attributed wiki commit message."""

    clean_action = _one_line_required(action, "action")
    clean_what = _one_line_required(what, "what")
    clean_author = _one_line_required(author, "author")
    return f"wiki: {clean_action} {clean_what} [{clean_author}]"


def commit_change(
    wiki_root: Path | str,
    *,
    action: str,
    what: str,
    author: str,
) -> GitCommitResult:
    """Stage durable wiki changes and create an attributed git commit if needed.

    Projection binaries are excluded explicitly in addition to being covered by
    ``.gitignore`` so callers can safely invoke this after projection rebuilds.
    """

    root = Path(wiki_root)
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        _git_init(root)
    ensure_gitignore(root)
    message = format_commit_message(action=action, what=what, author=author)

    changed_files = _changed_durable_files(root)
    if changed_files:
        _run_git(["add", "--all", "--", *changed_files], cwd=root)
    staged_files = tuple(_git_lines(root, "diff", "--cached", "--name-only", "--"))
    forbidden = tuple(path for path in staged_files if _is_projection_binary(path))
    if forbidden:
        raise GitOpsError(
            "refusing to commit projection binaries staged in wiki repository: "
            + ", ".join(forbidden)
        )
    if not staged_files:
        return GitCommitResult(
            repo_path=root,
            message=message,
            committed=False,
            commit_id=None,
            staged_files=(),
        )

    _run_git(
        [
            "-c",
            f"user.name={_git_identity_name(author)}",
            "-c",
            f"user.email={_git_identity_email(author)}",
            "commit",
            "--no-gpg-sign",
            "-m",
            message,
        ],
        cwd=root,
        env=_git_identity_env(author),
    )
    commit_id = _git_stdout(root, "rev-parse", "HEAD")
    return GitCommitResult(
        repo_path=root,
        message=message,
        committed=True,
        commit_id=commit_id,
        staged_files=staged_files,
    )


def _git_init(wiki_root: Path) -> None:
    result = _run_git(["init", "--initial-branch=main"], cwd=wiki_root, check=False)
    if result.returncode == 0:
        return
    _run_git(["init"], cwd=wiki_root)


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            env=command_env,
        )
    except FileNotFoundError as exc:  # pragma: no cover - mission precondition covers this
        raise GitOpsError("git executable was not found") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitOpsError(f"git {' '.join(args)} failed in {cwd}: {detail}")
    return result


def _git_stdout(cwd: Path, *args: str) -> str:
    return _run_git(list(args), cwd=cwd).stdout.strip()


def _git_lines(cwd: Path, *args: str) -> list[str]:
    output = _git_stdout(cwd, *args)
    if not output:
        return []
    return output.splitlines()


def _changed_durable_files(wiki_root: Path) -> list[str]:
    raw_status = _run_git(
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=wiki_root,
    ).stdout
    if not raw_status:
        return []
    paths: list[str] = []
    entries = raw_status.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        if not entry:
            index += 1
            continue
        status = entry[:2]
        path = entry[3:]
        if path and not _is_projection_binary(path):
            paths.append(path)
        index += 1
        if status[0] in {"R", "C"} or status[1] in {"R", "C"}:
            index += 1
    return paths


def _validate_slug(slug: str) -> str:
    clean_slug = _one_line_required(slug, "slug")
    if clean_slug in {".", ".."} or "/" in clean_slug or "\\" in clean_slug:
        raise ValueError(f"invalid wiki slug: {slug!r}")
    if Path(clean_slug).is_absolute():
        raise ValueError(f"invalid wiki slug: {slug!r}")
    return clean_slug


def _one_line_required(value: str, field: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{field} is required")
    if "\n" in clean_value or "\r" in clean_value:
        raise ValueError(f"{field} must be a single line")
    return clean_value


def _is_projection_binary(path: str) -> bool:
    return path in {
        "wiki.db",
        "wiki.db-shm",
        "wiki.db-wal",
        "wiki.db.tmp",
        "wiki.db.tmp-shm",
        "wiki.db.tmp-wal",
        "wiki.db.tmp.lock",
        ".ingest.lock",
    } or (
        path.startswith("db_versions/") and path.endswith(".db")
    )


def _git_identity_name(author: str) -> str:
    return _one_line_required(author, "author")


def _git_identity_email(author: str) -> str:
    local_part = _EMAIL_SAFE_RE.sub("-", author.strip().lower()).strip("-.") or "wiki"
    return f"{local_part}@hermes-wiki.invalid"


def _git_identity_env(author: str) -> dict[str, str]:
    name = _git_identity_name(author)
    email = _git_identity_email(author)
    return {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }


__all__ = [
    "GITIGNORE_ENTRIES",
    "GITIGNORE_MARKER",
    "GitCommitResult",
    "GitOpsError",
    "commit_change",
    "ensure_gitignore",
    "format_commit_message",
    "initialize_wiki_repo",
]
