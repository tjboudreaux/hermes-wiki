from __future__ import annotations


def grant_env_from_argv(argv: tuple[str, ...]) -> dict[str, str]:
    """Infer a scoped write grant from a CLI argument tuple containing ``--wiki``."""

    if "--wiki" not in argv:
        return {}
    index = argv.index("--wiki")
    if index + 1 >= len(argv):
        return {}
    return {"HERMES_WIKI": argv[index + 1]}
