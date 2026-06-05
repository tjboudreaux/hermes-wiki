/*
 * Hermes Wiki dashboard plugin.
 *
 * Built as a classic IIFE. React and the design-system components are supplied
 * by the Hermes Plugin SDK (the host dashboard's @nous-research/ui surface), so
 * this bundle does not include its own React runtime.
 */

declare global {
  interface Window {
    __HERMES_PLUGIN_SDK__?: HermesPluginSDK;
    __HERMES_PLUGINS__?: {
      register(name: string, component: unknown): void;
    };
  }
}

type WikiSummary = {
  slug: string;
  domain?: string | null;
  page_count: number;
  source_count: number;
  health_score: number;
  last_ingest?: string | null;
  last_lint?: string | null;
  created?: string | null;
  updated?: string | null;
};

type PageListItem = {
  id: string;
  title?: string | null;
  type?: string | null;
  tags?: string[];
  sources?: string[];
  snippet?: string | null;
  updated?: string | null;
  author?: string | null;
  author_kind?: string | null;
  inbound_links?: number;
};

type Pagination = {
  page: number;
  page_size: number;
  total: number;
  has_next: boolean;
  has_previous: boolean;
};

type PageListResponse = {
  wiki: string;
  items: PageListItem[];
  pagination: Pagination;
  filters: { type?: string | null; tag?: string | null };
};

type SearchResult = {
  wiki: string;
  id: string;
  title?: string | null;
  type?: string | null;
  tags?: string[];
  snippet?: string | null;
  rank?: number;
  score?: number;
  href?: string | null;
};

type SearchResponse = {
  wiki?: string | null;
  query: string;
  results: SearchResult[];
};

type InboxItem = {
  filename: string;
  name: string;
  path: string;
  status: string;
  classifier: string;
  suggested_class?: string | null;
  last_classification?: string | null;
  last_attempted_at?: string | null;
  size_bytes: number;
};

type ActivityEntry = {
  timestamp?: string | null;
  created?: string | null;
  action?: string | null;
  target?: string | null;
  page_id?: string | null;
  author?: string | null;
  author_kind?: string | null;
  details?: string | null;
};

type ActivityResponse = {
  wiki?: string;
  items: ActivityEntry[];
  pagination: Pagination;
  filters?: { author?: string | null; kind?: string | null };
};

type HealthFinding = {
  severity?: string;
  check?: string;
  code?: string;
  message?: string;
  page_id?: string;
  path?: string;
  target?: string;
};

type HealthReport = {
  health_score?: number;
  summary?: Record<string, number>;
  findings?: HealthFinding[];
};

type PageReference = {
  id: string;
  title?: string | null;
  type?: string | null;
  exists?: boolean;
};

type KanbanRef = {
  task_id?: string | null;
  title?: string | null;
  direction?: string | null;
  created?: string | null;
};

type WikiPageDetail = {
  wiki: string;
  id: string;
  page_id: string;
  title?: string | null;
  type?: string | null;
  markdown: string;
  body: string;
  frontmatter: Record<string, unknown>;
  inbound_links: number;
  outbound_links: string[];
  outbound_pages?: PageReference[];
  inbound_pages?: PageReference[];
  kanban_refs: KanbanRef[];
  history: ActivityEntry[];
  path?: string | null;
};

type HermesPluginSDK = {
  React: {
    createElement: (...args: unknown[]) => unknown;
  };
  hooks: {
    useCallback: <T extends (...args: never[]) => unknown>(callback: T, deps: unknown[]) => T;
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => void;
    useMemo: <T>(factory: () => T, deps: unknown[]) => T;
    useState: <T>(initial: T) => [T, (next: T | ((previous: T) => T)) => void];
  };
  fetchJSON: <T = unknown>(url: string, init?: RequestInit) => Promise<T>;
  components: Record<string, unknown>;
  utils?: {
    timeAgo?: (value?: string | null) => string;
  };
};

const SDK = window.__HERMES_PLUGIN_SDK__;

if (SDK && window.__HERMES_PLUGINS__) {
  const { React } = SDK;
  const h = React.createElement;
  const { useCallback, useEffect, useMemo, useState } = SDK.hooks;
  const components = SDK.components || {};
  const Card = (components.Card || "section") as string;
  const CardHeader = (components.CardHeader || "div") as string;
  const CardTitle = (components.CardTitle || "h3") as string;
  const CardContent = (components.CardContent || "div") as string;
  const Badge = (components.Badge || "span") as string;
  const Button = (components.Button || "button") as string;
  const Input = (components.Input || "input") as string;
  const timeAgo = SDK.utils?.timeAgo;

  function healthTone(score: number) {
    if (score >= 0.9) return "good";
    if (score >= 0.7) return "warn";
    return "bad";
  }

  function relativeTime(value?: string | null) {
    if (!value) return "never";
    if (timeAgo) {
      const rendered = timeAgo(value);
      if (rendered && !/NaN/i.test(rendered)) return rendered;
    }
    return value;
  }

  function formatScore(score?: number | null) {
    return Number(score || 0).toFixed(2);
  }

  function pathForWiki(slug: string) {
    return `/wikis/${encodeURIComponent(slug)}`;
  }

  function pathForPage(slug: string, pageId: string) {
    return `${pathForWiki(slug)}/${encodePageId(pageId)}`;
  }

  function pathForInbox(slug: string) {
    return `${pathForWiki(slug)}/inbox`;
  }

  function pathForHealth(slug: string) {
    return `${pathForWiki(slug)}/health`;
  }

  function pathForLog(slug: string) {
    return `${pathForWiki(slug)}/log`;
  }

  function pathForSearch(query = "", wiki = "") {
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (wiki.trim()) params.set("wiki", wiki.trim());
    const suffix = params.toString();
    return `/wikis/search${suffix ? `?${suffix}` : ""}`;
  }

  function encodePageId(pageId: string) {
    return pageId
      .split("/")
      .filter(Boolean)
      .map((part) => encodeURIComponent(part))
      .join("/");
  }

  function navigatePath(path: string) {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new Event("popstate"));
  }

  function onNavigate(path: string) {
    return (event: Event) => {
      event.preventDefault();
      navigatePath(path);
    };
  }

  function messageOf(error: unknown) {
    return error instanceof Error ? error.message : String(error);
  }

  function isNotFound(message: string) {
    return /404|not found|not visible/i.test(message);
  }

  function LoadingState(props: { label: string }) {
    return h("div", { className: "hermes-wiki-state", role: "status" }, props.label);
  }

  function EmptyState(props: { title: string; body: string }) {
    return h(
      Card,
      { className: "hermes-wiki-empty" },
      h(CardHeader, null, h(CardTitle, null, props.title)),
      h(CardContent, null, props.body),
    );
  }

  function ErrorState(props: { title: string; message: string; onRetry?: () => void }) {
    return h(
      Card,
      { className: "hermes-wiki-error", role: "alert" },
      h(CardHeader, null, h(CardTitle, null, props.title)),
      h(
        CardContent,
        null,
        h("p", null, props.message),
        props.onRetry ? h(Button, { onClick: props.onRetry }, "Retry") : null,
      ),
    );
  }

  function BackLink(props: { href: string; label: string }) {
    return h("a", { className: "hermes-wiki-back", href: props.href, onClick: onNavigate(props.href) }, props.label);
  }

  function WikiCard(props: { wiki: WikiSummary }) {
    const wiki = props.wiki;
    const score = Number(wiki.health_score || 0);
    return h(
      "a",
      {
        className: "hermes-wiki-card-link",
        href: pathForWiki(wiki.slug),
        onClick: onNavigate(pathForWiki(wiki.slug)),
        "data-wiki-card": wiki.slug,
      },
      h(
        Card,
        { className: "hermes-wiki-card" },
        h(
          CardHeader,
          { className: "hermes-wiki-card-header" },
          h(CardTitle, null, wiki.slug),
          h(Badge, { className: `hermes-wiki-health hermes-wiki-health-${healthTone(score)}` }, `Health ${formatScore(score)}`),
        ),
        h(
          CardContent,
          null,
          h("p", { className: "hermes-wiki-domain" }, wiki.domain || "No domain set"),
          h(
            "dl",
            { className: "hermes-wiki-metrics" },
            h("div", null, h("dt", null, "Pages"), h("dd", null, String(wiki.page_count || 0))),
            h("div", null, h("dt", null, "Sources"), h("dd", null, String(wiki.source_count || 0))),
            h("div", null, h("dt", null, "Last ingest"), h("dd", null, relativeTime(wiki.last_ingest))),
          ),
        ),
      ),
    );
  }

  function LandingRoute() {
    const [wikis, setWikis] = useState<WikiSummary[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string>("");
    const [query, setQuery] = useState<string>("");

    const load = useCallback(() => {
      setLoading(true);
      setError("");
      SDK.fetchJSON<WikiSummary[]>("/api/plugins/wiki/wikis")
        .then((rows) => setWikis(Array.isArray(rows) ? rows : []))
        .catch((err) => setError(messageOf(err)))
        .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
      load();
    }, [load]);

    const normalizedQuery = query.trim().toLowerCase();
    const filtered = useMemo(
      () =>
        wikis.filter((wiki) => {
          if (!normalizedQuery) return true;
          return `${wiki.slug} ${wiki.domain || ""}`.toLowerCase().includes(normalizedQuery);
        }),
      [wikis, normalizedQuery],
    );

    if (loading) return h(LoadingState, { label: "Loading Wikis…" });
    if (error) return h(ErrorState, { title: "Could not load Wikis", message: error, onRetry: load });

    return h(
      "main",
      { className: "hermes-wiki" },
      h(
        "header",
        { className: "hermes-wiki-hero" },
        h("div", null, h("p", { className: "hermes-wiki-eyebrow" }, "Hermes Wiki"), h("h1", null, "Wikis")),
        h(Badge, null, `${wikis.length} visible`),
      ),
      h(
        "div",
        { className: "hermes-wiki-toolbar" },
        h("a", { className: "hermes-wiki-action-link", href: pathForSearch(), onClick: onNavigate(pathForSearch()) }, "Global Search"),
        h(Input, {
          "aria-label": "Filter Wikis",
          placeholder: "Filter Wikis…",
          value: query,
          onChange: (event: Event) => setQuery((event.target as HTMLInputElement).value),
        }),
      ),
      filtered.length
        ? h("section", { className: "hermes-wiki-grid" }, ...filtered.map((wiki) => h(WikiCard, { key: wiki.slug, wiki })))
        : h(EmptyState, {
            title: wikis.length ? "No Wikis match that filter" : "No visible Wikis",
            body: wikis.length
              ? "Clear the filter to restore the full visible Wiki list."
              : "Create a Wiki from the API or CLI to make it appear in this dashboard tab.",
          }),
    );
  }

  function WikiRoute(props: { slug: string }) {
    const [summary, setSummary] = useState<WikiSummary | null>(null);
    const [pages, setPages] = useState<PageListResponse | null>(null);
    const [allPages, setAllPages] = useState<PageListItem[]>([]);
    const [activity, setActivity] = useState<ActivityEntry[]>([]);
    const [health, setHealth] = useState<HealthReport | null>(null);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string>("");
    const [pageNumber, setPageNumber] = useState<number>(1);
    const [typeFilter, setTypeFilter] = useState<string>("");
    const [tagFilter, setTagFilter] = useState<string>("");

    const load = useCallback(() => {
      setLoading(true);
      setError("");
      Promise.all([
        SDK.fetchJSON<WikiSummary>(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}`),
        SDK.fetchJSON<PageListResponse>(pageListUrl(props.slug, pageNumber, typeFilter, tagFilter)),
        SDK.fetchJSON<PageListResponse>(pageListUrl(props.slug, 1, "", "", 200)),
        SDK.fetchJSON<ActivityResponse>(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/log?page_size=5`),
        SDK.fetchJSON<HealthReport>(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/health`),
      ])
        .then(([wikiRow, pageRows, allRows, logRows, healthRows]) => {
          setSummary(wikiRow);
          setPages(pageRows);
          setAllPages(allRows.items || []);
          setActivity(logRows.items || []);
          setHealth(healthRows);
        })
        .catch((err) => setError(messageOf(err)))
        .finally(() => setLoading(false));
    }, [props.slug, pageNumber, typeFilter, tagFilter]);

    useEffect(() => {
      load();
    }, [load]);

    const typeOptions = useMemo(() => sortedUnique(allPages.map((page) => page.type || "").filter(Boolean)), [allPages]);
    const tagOptions = useMemo(
      () => sortedUnique(allPages.flatMap((page) => page.tags || []).filter(Boolean)),
      [allPages],
    );

    if (loading) return h(LoadingState, { label: "Loading Wiki…" });
    if (error) {
      if (isNotFound(error)) return h(ErrorState, { title: "Wiki not found", message: "This Wiki was not found or is not visible." });
      return h(ErrorState, { title: "Failed to load Wiki", message: error, onRetry: load });
    }
    if (!summary || !pages) return h(EmptyState, { title: "Wiki unavailable", body: "No Wiki data was returned." });

    const score = Number(summary.health_score || health?.health_score || 0);
    const canReset = Boolean(typeFilter || tagFilter);

    return h(
      "main",
      { className: "hermes-wiki" },
      h(BackLink, { href: "/wikis", label: "← All Wikis" }),
      h(
        "header",
        { className: "hermes-wiki-detail-hero" },
        h(
          "div",
          null,
          h("p", { className: "hermes-wiki-eyebrow" }, "Wiki"),
          h("h1", null, summary.slug),
          h("p", { className: "hermes-wiki-domain" }, summary.domain || "No domain set"),
        ),
        h(
          "div",
          { className: "hermes-wiki-health-panel" },
          h("a", { className: "hermes-wiki-action-link", href: pathForSearch("", summary.slug), onClick: onNavigate(pathForSearch("", summary.slug)) }, "Search this Wiki"),
          h("a", { className: "hermes-wiki-action-link", href: pathForInbox(summary.slug), onClick: onNavigate(pathForInbox(summary.slug)) }, "Inbox"),
          h("a", { className: "hermes-wiki-action-link", href: pathForHealth(summary.slug), onClick: onNavigate(pathForHealth(summary.slug)) }, "Health"),
          h("a", { className: "hermes-wiki-action-link", href: pathForLog(summary.slug), onClick: onNavigate(pathForLog(summary.slug)) }, "Activity"),
          h(Badge, { className: `hermes-wiki-health hermes-wiki-health-${healthTone(score)}` }, `Health ${formatScore(score)}`),
          h("span", null, `${summary.page_count} pages`),
          h("span", null, `Last ingest ${relativeTime(summary.last_ingest)}`),
        ),
      ),
      h(
        "section",
        { className: "hermes-wiki-split" },
        h(
          Card,
          { className: "hermes-wiki-list-card" },
          h(
            CardHeader,
            { className: "hermes-wiki-card-header" },
            h(CardTitle, null, "Pages"),
            h(Badge, null, `${pages.pagination.total} total`),
          ),
          h(
            CardContent,
            null,
            h(
              "div",
              { className: "hermes-wiki-filters" },
              h(
                "label",
                null,
                "Type",
                h(
                  "select",
                  {
                    value: typeFilter,
                    onChange: (event: Event) => {
                      setTypeFilter((event.target as HTMLSelectElement).value);
                      setPageNumber(1);
                    },
                  },
                  h("option", { value: "" }, "All types"),
                  ...typeOptions.map((type) => h("option", { key: type, value: type }, type)),
                ),
              ),
              h(
                "label",
                null,
                "Tag",
                h(
                  "select",
                  {
                    value: tagFilter,
                    onChange: (event: Event) => {
                      setTagFilter((event.target as HTMLSelectElement).value);
                      setPageNumber(1);
                    },
                  },
                  h("option", { value: "" }, "All tags"),
                  ...tagOptions.map((tag) => h("option", { key: tag, value: tag }, tag)),
                ),
              ),
              h(
                Button,
                {
                  disabled: !canReset,
                  onClick: () => {
                    setTypeFilter("");
                    setTagFilter("");
                    setPageNumber(1);
                  },
                },
                "Reset filters",
              ),
            ),
            pages.items.length
              ? h("div", { className: "hermes-wiki-page-list" }, ...pages.items.map((page) => h(PageListRow, { key: page.id, slug: props.slug, page })))
              : h(EmptyState, { title: "No pages found", body: "No pages match the current filters." }),
            h(PaginationControls, { pagination: pages.pagination, onPage: setPageNumber }),
          ),
        ),
        h(
          "aside",
          { className: "hermes-wiki-side-stack" },
          h(HealthCard, { score, health, slug: summary.slug }),
          h(ActivityTimeline, { entries: activity, slug: summary.slug }),
        ),
      ),
    );
  }

  function pageListUrl(slug: string, page: number, typeFilter: string, tagFilter: string, pageSize = 5) {
    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    if (typeFilter) params.set("type", typeFilter);
    if (tagFilter) params.set("tag", tagFilter);
    return `/api/plugins/wiki/wikis/${encodeURIComponent(slug)}/pages?${params.toString()}`;
  }

  function sortedUnique(values: string[]) {
    return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b));
  }

  function PageListRow(props: { slug: string; page: PageListItem }) {
    const page = props.page;
    return h(
      "a",
      {
        className: "hermes-wiki-page-row",
        href: pathForPage(props.slug, page.id),
        onClick: onNavigate(pathForPage(props.slug, page.id)),
        "data-page-id": page.id,
      },
      h(
        "div",
        null,
        h("strong", null, page.title || page.id),
        h("p", null, page.snippet || page.id),
        h(
          "div",
          { className: "hermes-wiki-tags" },
          h(Badge, null, page.type || "page"),
          ...(page.tags || []).map((tag) => h(Badge, { key: tag }, tag)),
        ),
      ),
      h("span", { className: "hermes-wiki-muted" }, relativeTime(page.updated)),
    );
  }

  function PaginationControls(props: { pagination: Pagination; onPage: (page: number) => void }) {
    const pagination = props.pagination;
    if (pagination.total <= pagination.page_size) {
      return h("div", { className: "hermes-wiki-pagination" }, `Page ${pagination.page} of 1`);
    }
    const pageCount = Math.max(1, Math.ceil(pagination.total / pagination.page_size));
    return h(
      "div",
      { className: "hermes-wiki-pagination", "aria-label": "Pagination" },
      h(Button, { disabled: !pagination.has_previous, onClick: () => props.onPage(Math.max(1, pagination.page - 1)) }, "Previous"),
      h("span", null, `Page ${pagination.page} of ${pageCount}`),
      h(Button, { disabled: !pagination.has_next, onClick: () => props.onPage(pagination.page + 1) }, "Next"),
    );
  }

  function HealthCard(props: { score: number; health: HealthReport | null; slug?: string }) {
    const summary = props.health?.summary || {};
    const severities = Object.entries(summary).filter(([_key, value]) => Number(value) > 0);
    return h(
      Card,
      null,
      h(CardHeader, null, h(CardTitle, null, "Health")),
      h(
        CardContent,
        { className: "hermes-wiki-health-card" },
        h(Badge, { className: `hermes-wiki-health hermes-wiki-health-${healthTone(props.score)}` }, `Score ${formatScore(props.score)}`),
        severities.length
          ? h("ul", null, ...severities.map(([severity, count]) => h("li", { key: severity }, `${severity}: ${count}`)))
          : h("p", null, "No lint findings reported."),
        props.slug
          ? h("a", { className: "hermes-wiki-action-link", href: pathForHealth(props.slug), onClick: onNavigate(pathForHealth(props.slug)) }, "Open Health")
          : null,
      ),
    );
  }

  function ActivityTimeline(props: { entries: ActivityEntry[]; slug?: string }) {
    return h(
      Card,
      null,
      h(CardHeader, null, h(CardTitle, null, "Recent Activity")),
      h(
        CardContent,
        null,
        props.entries.length
          ? h(
              "ol",
              { className: "hermes-wiki-timeline" },
              ...props.entries.map((entry, index) =>
                h(
                  "li",
                  { key: `${entry.timestamp || entry.created || "entry"}-${index}` },
                  h("strong", null, entry.action || "change"),
                  h("span", null, entry.target || entry.page_id || "wiki"),
                  h("small", null, `${entry.author || "unknown"} · ${entry.author_kind || "unknown"} · ${relativeTime(entry.timestamp || entry.created)}`),
                ),
              ),
            )
          : h("p", null, "No activity recorded yet."),
        props.slug
          ? h("a", { className: "hermes-wiki-action-link", href: pathForLog(props.slug), onClick: onNavigate(pathForLog(props.slug)) }, "Open Activity")
          : null,
      ),
    );
  }

  function severityLabel(severity?: string | null) {
    const value = (severity || "low").toLowerCase();
    if (value === "high") return "🔴 high";
    if (value === "medium") return "⚠️ medium";
    return "💡 low";
  }

  function severityClass(severity?: string | null) {
    const value = (severity || "low").toLowerCase();
    if (value === "high") return "hermes-wiki-health-bad";
    if (value === "medium") return "hermes-wiki-health-warn";
    return "hermes-wiki-health-good";
  }

  function HealthRoute(props: { slug: string }) {
    const [summary, setSummary] = useState<WikiSummary | null>(null);
    const [report, setReport] = useState<HealthReport | null>(null);
    const [selectedSeverities, setSelectedSeverities] = useState<string[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string>("");

    const load = useCallback(() => {
      setLoading(true);
      setError("");
      Promise.all([
        SDK.fetchJSON<WikiSummary>(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}`),
        SDK.fetchJSON<HealthReport>(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/health`),
      ])
        .then(([wikiRow, healthRows]) => {
          setSummary(wikiRow);
          setReport(healthRows);
        })
        .catch((err) => setError(messageOf(err)))
        .finally(() => setLoading(false));
    }, [props.slug]);

    useEffect(() => {
      load();
    }, [load]);

    const findings = report?.findings || [];
    const counts = report?.summary || {};
    const filteredFindings = useMemo(() => {
      if (!selectedSeverities.length) return findings;
      const selected = new Set(selectedSeverities);
      return findings.filter((finding) => selected.has((finding.severity || "low").toLowerCase()));
    }, [findings, selectedSeverities]);

    const toggleSeverity = (severity: string) => {
      setSelectedSeverities((previous) =>
        previous.includes(severity) ? previous.filter((item) => item !== severity) : previous.concat(severity),
      );
    };

    if (loading) return h(LoadingState, { label: "Loading Health…" });
    if (error) {
      if (isNotFound(error)) {
        return h(
          "main",
          { className: "hermes-wiki" },
          h(BackLink, { href: pathForWiki(props.slug), label: "← Back to Wiki" }),
          h(ErrorState, { title: "Health report not found", message: "This Wiki health report was not found or is not visible." }),
        );
      }
      return h(ErrorState, { title: "Failed to load Health", message: error, onRetry: load });
    }

    const score = Number(report?.health_score ?? summary?.health_score ?? 0);
    const allSelected = selectedSeverities.length === 0;

    return h(
      "main",
      { className: "hermes-wiki" },
      h(BackLink, { href: pathForWiki(props.slug), label: "← Back to Wiki" }),
      h(
        "header",
        { className: "hermes-wiki-detail-hero" },
        h(
          "div",
          null,
          h("p", { className: "hermes-wiki-eyebrow" }, "Wiki Health"),
          h("h1", null, `${summary?.slug || props.slug} Health`),
          h("p", { className: "hermes-wiki-domain" }, "Lint findings and consistency checks"),
        ),
        h(
          "div",
          { className: "hermes-wiki-health-panel" },
          h(Badge, { className: `hermes-wiki-health hermes-wiki-health-${healthTone(score)}` }, `Score ${formatScore(score)}`),
          h(Badge, null, `${findings.length} findings`),
        ),
      ),
      h(
        Card,
        null,
        h(CardHeader, null, h(CardTitle, null, "Severity filters")),
        h(
          CardContent,
          null,
          h(
            "div",
            { className: "hermes-wiki-severity-filters", "aria-label": "Filter lint findings by severity" },
            ...["high", "medium", "low"].map((severity) =>
              h(
                "label",
                { key: severity },
                h("input", {
                  type: "checkbox",
                  checked: selectedSeverities.includes(severity),
                  onChange: () => toggleSeverity(severity),
                }),
                `${severityLabel(severity)} (${Number(counts[severity] || 0)})`,
              ),
            ),
            h(Button, { disabled: allSelected, onClick: () => setSelectedSeverities([]) }, "Clear severity filters"),
          ),
        ),
      ),
      findings.length === 0
        ? h(EmptyState, { title: "Healthy Wiki", body: "No lint findings were reported for this Wiki." })
        : filteredFindings.length
          ? h(
              "section",
              { className: "hermes-wiki-finding-list", "data-testid": "wiki-health-findings" },
              ...filteredFindings.map((finding, index) => h(HealthFindingRow, { key: `${finding.check || finding.code || "finding"}-${index}`, finding })),
            )
          : h(EmptyState, {
              title: "No findings match those severities",
              body: "Select additional severities or clear filters to restore the full lint report.",
            }),
    );
  }

  function HealthFindingRow(props: { finding: HealthFinding }) {
    const finding = props.finding;
    const severity = (finding.severity || "low").toLowerCase();
    const target = finding.page_id || finding.target || finding.path || "";
    return h(
      Card,
      { className: "hermes-wiki-finding", "data-severity": severity },
      h(
        CardHeader,
        { className: "hermes-wiki-card-header" },
        h(CardTitle, null, finding.check || finding.code || "lint finding"),
        h(Badge, { className: severityClass(severity) }, severityLabel(severity)),
      ),
      h(
        CardContent,
        null,
        h("p", null, finding.message || "No finding message was provided."),
        target ? h("p", { className: "hermes-wiki-muted" }, target) : null,
      ),
    );
  }

  function ActivityRoute(props: { slug: string }) {
    const [summary, setSummary] = useState<WikiSummary | null>(null);
    const [entries, setEntries] = useState<ActivityEntry[]>([]);
    const [allEntries, setAllEntries] = useState<ActivityEntry[]>([]);
    const [pagination, setPagination] = useState<Pagination | null>(null);
    const [authorFilter, setAuthorFilter] = useState<string>("");
    const [kindFilter, setKindFilter] = useState<string>("");
    const [pageNumber, setPageNumber] = useState<number>(1);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string>("");

    const load = useCallback(() => {
      setLoading(true);
      setError("");
      Promise.all([
        SDK.fetchJSON<WikiSummary>(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}`),
        SDK.fetchJSON<ActivityResponse>(activityUrl(props.slug, pageNumber, authorFilter, kindFilter, 5)),
        SDK.fetchJSON<ActivityResponse>(activityUrl(props.slug, 1, "", "", 200)),
      ])
        .then(([wikiRow, logRows, allRows]) => {
          setSummary(wikiRow);
          setEntries(Array.isArray(logRows.items) ? logRows.items : []);
          setPagination(logRows.pagination);
          setAllEntries(Array.isArray(allRows.items) ? allRows.items : []);
        })
        .catch((err) => setError(messageOf(err)))
        .finally(() => setLoading(false));
    }, [props.slug, pageNumber, authorFilter, kindFilter]);

    useEffect(() => {
      load();
    }, [load]);

    const authorOptions = useMemo(
      () => sortedUnique(allEntries.map((entry) => entry.author || "").filter(Boolean)),
      [allEntries],
    );
    const kindOptions = useMemo(
      () => sortedUnique(allEntries.map((entry) => entry.author_kind || "").filter(Boolean)),
      [allEntries],
    );

    if (loading) return h(LoadingState, { label: "Loading Activity…" });
    if (error) {
      if (isNotFound(error)) {
        return h(
          "main",
          { className: "hermes-wiki" },
          h(BackLink, { href: pathForWiki(props.slug), label: "← Back to Wiki" }),
          h(ErrorState, { title: "Activity log not found", message: "This Wiki activity log was not found or is not visible." }),
        );
      }
      return h(ErrorState, { title: "Failed to load Activity", message: error, onRetry: load });
    }

    const canReset = Boolean(authorFilter || kindFilter);

    return h(
      "main",
      { className: "hermes-wiki" },
      h(BackLink, { href: pathForWiki(props.slug), label: "← Back to Wiki" }),
      h(
        "header",
        { className: "hermes-wiki-detail-hero" },
        h(
          "div",
          null,
          h("p", { className: "hermes-wiki-eyebrow" }, "Wiki Activity"),
          h("h1", null, `${summary?.slug || props.slug} Activity`),
          h("p", { className: "hermes-wiki-domain" }, "Chronological attributed changes"),
        ),
        h(Badge, null, `${pagination?.total ?? entries.length} entries`),
      ),
      h(
        Card,
        null,
        h(CardHeader, null, h(CardTitle, null, "Activity filters")),
        h(
          CardContent,
          null,
          h(
            "div",
            { className: "hermes-wiki-filters" },
            h(
              "label",
              null,
              "Author",
              h(
                "select",
                {
                  value: authorFilter,
                  onChange: (event: Event) => {
                    setAuthorFilter((event.target as HTMLSelectElement).value);
                    setPageNumber(1);
                  },
                },
                h("option", { value: "" }, "All authors"),
                ...authorOptions.map((author) => h("option", { key: author, value: author }, author)),
              ),
            ),
            h(
              "label",
              null,
              "Kind",
              h(
                "select",
                {
                  value: kindFilter,
                  onChange: (event: Event) => {
                    setKindFilter((event.target as HTMLSelectElement).value);
                    setPageNumber(1);
                  },
                },
                h("option", { value: "" }, "All kinds"),
                ...kindOptions.map((kind) => h("option", { key: kind, value: kind }, kind)),
              ),
            ),
            h(
              Button,
              {
                disabled: !canReset,
                onClick: () => {
                  setAuthorFilter("");
                  setKindFilter("");
                  setPageNumber(1);
                },
              },
              "Reset filters",
            ),
          ),
        ),
      ),
      entries.length
        ? h(
            "section",
            { className: "hermes-wiki-activity-list", "data-testid": "wiki-activity-log" },
            h(
              "ol",
              { className: "hermes-wiki-timeline" },
              ...entries.map((entry, index) => h(ActivityLogRow, { key: `${entry.timestamp || entry.created || "entry"}-${index}`, entry })),
            ),
            pagination ? h(PaginationControls, { pagination, onPage: setPageNumber }) : null,
          )
        : h(EmptyState, {
            title: "No activity entries",
            body: canReset ? "No activity entries match the selected filters." : "No activity has been recorded for this Wiki yet.",
          }),
    );
  }

  function activityUrl(slug: string, page: number, author: string, kind: string, pageSize: number) {
    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    if (author) params.set("author", author);
    if (kind) params.set("kind", kind);
    return `/api/plugins/wiki/wikis/${encodeURIComponent(slug)}/log?${params.toString()}`;
  }

  function ActivityLogRow(props: { entry: ActivityEntry }) {
    const entry = props.entry;
    return h(
      "li",
      {
        "data-author": entry.author || "",
        "data-author-kind": entry.author_kind || "",
        "data-timestamp": entry.timestamp || entry.created || "",
      },
      h("strong", null, entry.action || "change"),
      h("span", null, entry.target || entry.page_id || "wiki"),
      h("small", null, `${entry.author || "unknown"} · ${entry.author_kind || "unknown"} · ${entry.timestamp || entry.created || "unknown time"}`),
      entry.details ? h("span", { className: "hermes-wiki-muted" }, entry.details) : null,
    );
  }

  function PageRoute(props: { slug: string; pageId: string }) {
    const [page, setPage] = useState<WikiPageDetail | null>(null);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string>("");

    const load = useCallback(() => {
      setLoading(true);
      setError("");
      SDK.fetchJSON<WikiPageDetail>(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/pages/${encodePageId(props.pageId)}`)
        .then((row) => setPage(row))
        .catch((err) => setError(messageOf(err)))
        .finally(() => setLoading(false));
    }, [props.slug, props.pageId]);

    useEffect(() => {
      load();
    }, [load]);

    if (loading) return h(LoadingState, { label: "Loading Page…" });
    if (error) {
      if (isNotFound(error)) {
        return h(
          "main",
          { className: "hermes-wiki" },
          h(BackLink, { href: pathForWiki(props.slug), label: "← Back to Wiki" }),
          h(ErrorState, { title: "Page not found", message: "This page was not found or is not visible." }),
        );
      }
      return h(ErrorState, { title: "Failed to load Page", message: error, onRetry: load });
    }
    if (!page) return h(EmptyState, { title: "Page unavailable", body: "No page data was returned." });

    return h(
      "main",
      { className: "hermes-wiki" },
      h(BackLink, { href: pathForWiki(props.slug), label: "← Back to Wiki" }),
      h(
        "header",
        { className: "hermes-wiki-detail-hero" },
        h(
          "div",
          null,
          h("p", { className: "hermes-wiki-eyebrow" }, page.type || "Wiki Page"),
          h("h1", null, page.title || page.id),
          h("p", { className: "hermes-wiki-muted" }, page.id),
        ),
        h(Badge, null, page.frontmatter?.confidence ? `Confidence ${String(page.frontmatter.confidence)}` : page.type || "page"),
      ),
      h(
        "section",
        { className: "hermes-wiki-page-layout" },
        h(
          "article",
          { className: "hermes-wiki-page-body", "data-testid": "wiki-page-body" },
          h(MarkdownBody, { markdown: page.body || page.markdown || "", slug: props.slug, pageId: page.id }),
        ),
        h(
          "aside",
          { className: "hermes-wiki-page-sidebar" },
          h(FrontmatterPanel, { frontmatter: page.frontmatter }),
          h(LinkPanel, { title: "Outbound Links", slug: props.slug, links: page.outbound_pages || refsFromIds(page.outbound_links) }),
          h(LinkPanel, { title: "Inbound Links", slug: props.slug, links: page.inbound_pages || [] }),
          h(KanbanPanel, { refs: page.kanban_refs || [] }),
          h(HistoryPanel, { entries: page.history || [] }),
        ),
      ),
    );
  }

  function refsFromIds(ids: string[]) {
    return ids.map((id) => ({ id, title: id, exists: true }));
  }

  function FrontmatterPanel(props: { frontmatter: Record<string, unknown> }) {
    const preferred = ["title", "type", "tags", "confidence", "sources", "author", "author_kind", "created", "updated"];
    const keys = preferred.filter((key) => props.frontmatter[key] !== undefined && props.frontmatter[key] !== null);
    return h(
      Card,
      null,
      h(CardHeader, null, h(CardTitle, null, "Frontmatter")),
      h(
        CardContent,
        null,
        h(
          "dl",
          { className: "hermes-wiki-frontmatter" },
          ...keys.flatMap((key) => [h("dt", { key: `${key}-dt` }, key), h("dd", { key: `${key}-dd` }, formatMetadata(props.frontmatter[key]))]),
        ),
      ),
    );
  }

  function formatMetadata(value: unknown) {
    if (Array.isArray(value)) return value.join(", ");
    if (typeof value === "object" && value !== null) return JSON.stringify(value);
    return String(value);
  }

  function LinkPanel(props: { title: string; slug: string; links: PageReference[] }) {
    return h(
      Card,
      null,
      h(CardHeader, null, h(CardTitle, null, props.title)),
      h(
        CardContent,
        null,
        props.links.length
          ? h(
              "ul",
              { className: "hermes-wiki-link-list" },
              ...props.links.map((link) =>
                h(
                  "li",
                  { key: link.id },
                  h(
                    "a",
                    { href: pathForPage(props.slug, link.id), onClick: onNavigate(pathForPage(props.slug, link.id)) },
                    link.title || link.id,
                  ),
                  link.type ? h(Badge, null, link.type) : null,
                  link.exists === false ? h(Badge, { className: "hermes-wiki-health-bad" }, "missing") : null,
                ),
              ),
            )
          : h("p", null, "None"),
      ),
    );
  }

  function KanbanPanel(props: { refs: KanbanRef[] }) {
    return h(
      Card,
      null,
      h(CardHeader, null, h(CardTitle, null, "Linked Kanban Tasks")),
      h(
        CardContent,
        null,
        props.refs.length
          ? h(
              "ul",
              { className: "hermes-wiki-link-list" },
              ...props.refs.map((ref, index) =>
                h("li", { key: `${ref.task_id || "task"}-${index}` }, h("strong", null, ref.task_id || "task"), h("span", null, ref.title || ref.direction || "linked")),
              ),
            )
          : h("p", null, "No linked kanban tasks."),
      ),
    );
  }

  function HistoryPanel(props: { entries: ActivityEntry[] }) {
    return h(
      Card,
      { className: "hermes-wiki-history", "data-testid": "wiki-page-history" },
      h(CardHeader, null, h(CardTitle, null, "Page History")),
      h(
        CardContent,
        null,
        props.entries.length
          ? h(
              "ol",
              { className: "hermes-wiki-timeline" },
              ...props.entries.map((entry, index) =>
                h(
                  "li",
                  { key: `${entry.timestamp || entry.created || "history"}-${index}` },
                  h("strong", null, entry.action || "change"),
                  h("span", null, entry.target || entry.page_id || "page"),
                  h("small", null, `${entry.author || "unknown"} · ${entry.author_kind || "unknown"} · ${relativeTime(entry.timestamp || entry.created)}`),
                ),
              ),
            )
          : h("p", null, "No page history recorded."),
      ),
    );
  }

  function MarkdownBody(props: { markdown: string; slug: string; pageId: string }) {
    return h("div", { className: "hermes-wiki-markdown" }, ...renderMarkdownBlocks(props.markdown, props.slug, props.pageId));
  }

  function SearchRoute(props: { query: string; scope: string }) {
    const [wikis, setWikis] = useState<WikiSummary[]>([]);
    const [query, setQuery] = useState<string>(props.query);
    const [scope, setScope] = useState<string>(props.scope);
    const [results, setResults] = useState<SearchResult[]>([]);
    const [loading, setLoading] = useState<boolean>(false);
    const [error, setError] = useState<string>("");

    useEffect(() => {
      setQuery(props.query);
      setScope(props.scope);
    }, [props.query, props.scope]);

    useEffect(() => {
      SDK.fetchJSON<WikiSummary[]>("/api/plugins/wiki/wikis")
        .then((rows) => setWikis(Array.isArray(rows) ? rows : []))
        .catch(() => setWikis([]));
    }, []);

    const load = useCallback(() => {
      const trimmed = props.query.trim();
      setError("");
      if (!trimmed) {
        setResults([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      const params = new URLSearchParams({ q: trimmed, limit: "20" });
      const url = props.scope
        ? `/api/plugins/wiki/wikis/${encodeURIComponent(props.scope)}/search?${params.toString()}`
        : `/api/plugins/wiki/search?${params.toString()}`;
      SDK.fetchJSON<SearchResponse>(url)
        .then((row) => setResults(Array.isArray(row.results) ? row.results : []))
        .catch((err) => setError(messageOf(err)))
        .finally(() => setLoading(false));
    }, [props.query, props.scope]);

    useEffect(() => {
      load();
    }, [load]);

    const submit = (event: Event) => {
      event.preventDefault();
      navigatePath(pathForSearch(query, scope));
    };

    return h(
      "main",
      { className: "hermes-wiki" },
      h(BackLink, { href: "/wikis", label: "← All Wikis" }),
      h(
        "header",
        { className: "hermes-wiki-detail-hero" },
        h(
          "div",
          null,
          h("p", { className: "hermes-wiki-eyebrow" }, "Wiki Search"),
          h("h1", null, "Search Wikis"),
          h("p", { className: "hermes-wiki-domain" }, scope ? `Scoped to ${scope}` : "Across all visible Wikis"),
        ),
        h(Badge, null, props.query ? `${results.length} results` : "BM25 ranked"),
      ),
      h(
        "form",
        { className: "hermes-wiki-search-form", onSubmit: submit },
        h(Input, {
          "aria-label": "Search query",
          placeholder: "Search pages…",
          value: query,
          onChange: (event: Event) => setQuery((event.target as HTMLInputElement).value),
        }),
        h(
          "select",
          {
            "aria-label": "Search scope",
            value: scope,
            onChange: (event: Event) => setScope((event.target as HTMLSelectElement).value),
          },
          h("option", { value: "" }, "All visible Wikis"),
          ...wikis.map((wiki) => h("option", { key: wiki.slug, value: wiki.slug }, wiki.slug)),
        ),
        h(Button, { type: "submit" }, "Search"),
      ),
      loading
        ? h(LoadingState, { label: "Searching Wikis…" })
        : error
          ? h(ErrorState, { title: "Search failed", message: error, onRetry: load })
          : !props.query.trim()
            ? h(EmptyState, { title: "Search all visible Wikis", body: "Enter a term to search Wiki pages with BM25 ranking." })
            : results.length
              ? h("section", { className: "hermes-wiki-result-list" }, ...results.map((result) => h(SearchResultRow, { key: `${result.wiki}:${result.id}`, result })))
              : h(EmptyState, { title: "No results", body: "No visible Wiki pages matched that query." }),
    );
  }

  function SearchResultRow(props: { result: SearchResult }) {
    const result = props.result;
    const href = result.href || pathForPage(result.wiki, result.id);
    return h(
      "a",
      {
        className: "hermes-wiki-result-row",
        href,
        onClick: onNavigate(href),
        "data-search-result": `${result.wiki}:${result.id}`,
      },
      h(
        Card,
        null,
        h(
          CardHeader,
          { className: "hermes-wiki-card-header" },
          h(CardTitle, null, result.title || result.id),
          h("div", { className: "hermes-wiki-tags" }, h(Badge, null, result.wiki), h(Badge, null, result.type || "page")),
        ),
        h(
          CardContent,
          null,
          h("p", null, result.snippet || result.id),
          h("small", { className: "hermes-wiki-muted" }, `BM25 rank ${Number(result.rank || result.score || 0).toFixed(4)}`),
        ),
      ),
    );
  }

  function InboxRoute(props: { slug: string }) {
    const [summary, setSummary] = useState<WikiSummary | null>(null);
    const [items, setItems] = useState<InboxItem[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string>("");
    const [busyFile, setBusyFile] = useState<string>("");
    const [busyIngest, setBusyIngest] = useState<boolean>(false);
    const [notice, setNotice] = useState<string>("");

    const load = useCallback(() => {
      setLoading(true);
      setError("");
      Promise.all([
        SDK.fetchJSON<WikiSummary>(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}`),
        SDK.fetchJSON<InboxItem[]>(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/inbox`),
      ])
        .then(([wikiRow, inboxRows]) => {
          setSummary(wikiRow);
          setItems(Array.isArray(inboxRows) ? inboxRows : []);
        })
        .catch((err) => setError(messageOf(err)))
        .finally(() => setLoading(false));
    }, [props.slug]);

    useEffect(() => {
      load();
    }, [load]);

    const overrideClassifier = (filename: string, classifier: string) => {
      setBusyFile(filename);
      setError("");
      setNotice("");
      SDK.fetchJSON<InboxItem>(
        `/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/inbox/${encodeURIComponent(filename)}/classify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ classifier }),
        },
      )
        .then((updated) => {
          setItems((previous) => previous.map((item) => (item.filename === updated.filename ? updated : item)));
        })
        .catch((err) => setError(messageOf(err)))
        .finally(() => setBusyFile(""));
    };

    const processInbox = () => {
      setBusyIngest(true);
      setError("");
      setNotice("");
      SDK.fetchJSON<{ results?: Array<{ pages_created?: string[]; pages_updated?: string[] }> }>(
        `/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/ingest`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ inbox: true }),
        },
      )
        .then((result) => {
          const changedPages = (result.results || []).reduce(
            (count, row) => count + (row.pages_created || []).length + (row.pages_updated || []).length,
            0,
          );
          setNotice(changedPages ? `Processed inbox and updated ${changedPages} page${changedPages === 1 ? "" : "s"}.` : "Inbox processed; no pages changed.");
          load();
        })
        .catch((err) => setError(messageOf(err)))
        .finally(() => setBusyIngest(false));
    };

    if (loading) return h(LoadingState, { label: "Loading Inbox…" });
    if (error && !items.length) {
      if (isNotFound(error)) {
        return h(
          "main",
          { className: "hermes-wiki" },
          h(BackLink, { href: pathForWiki(props.slug), label: "← Back to Wiki" }),
          h(ErrorState, { title: "Inbox not found", message: "This Wiki inbox was not found or is not visible." }),
        );
      }
      return h(ErrorState, { title: "Failed to load Inbox", message: error, onRetry: load });
    }

    return h(
      "main",
      { className: "hermes-wiki" },
      h(BackLink, { href: pathForWiki(props.slug), label: "← Back to Wiki" }),
      h(
        "header",
        { className: "hermes-wiki-detail-hero" },
        h(
          "div",
          null,
          h("p", { className: "hermes-wiki-eyebrow" }, "Wiki Inbox"),
          h("h1", null, `${summary?.slug || props.slug} Inbox`),
          h("p", { className: "hermes-wiki-domain" }, "Unprocessed raw files and classifier assignments"),
        ),
        h(
          "div",
          { className: "hermes-wiki-health-panel" },
          h(Badge, null, `${items.length} pending`),
          h(Button, { disabled: !items.length || busyIngest, onClick: processInbox }, busyIngest ? "Processing…" : "Process Inbox"),
        ),
      ),
      error ? h(ErrorState, { title: "Inbox update failed", message: error, onRetry: load }) : null,
      notice ? h(Card, { className: "hermes-wiki-notice" }, h(CardContent, null, notice)) : null,
      items.length
        ? h(
            "section",
            { className: "hermes-wiki-inbox-list" },
            ...items.map((item) =>
              h(InboxItemRow, {
                key: item.filename,
                item,
                busy: busyFile === item.filename,
                onOverride: overrideClassifier,
              }),
            ),
          )
        : h(EmptyState, { title: "Inbox is empty", body: "There are no unprocessed files in raw/inbox for this Wiki." }),
    );
  }

  function InboxItemRow(props: { item: InboxItem; busy: boolean; onOverride: (filename: string, classifier: string) => void }) {
    const item = props.item;
    const oversized = item.status === "oversized" || item.classifier === "oversized";
    const classes = ["article", "paper", "transcript", "unknown"];
    return h(
      Card,
      { className: oversized ? "hermes-wiki-inbox-item hermes-wiki-inbox-oversized" : "hermes-wiki-inbox-item" },
      h(
        CardHeader,
        { className: "hermes-wiki-card-header" },
        h(
          "div",
          null,
          h(CardTitle, null, item.filename),
          h("p", { className: "hermes-wiki-muted" }, item.path),
        ),
        h("div", { className: "hermes-wiki-tags" }, h(Badge, null, item.classifier || "unknown"), h(Badge, { className: oversized ? "hermes-wiki-health-bad" : "" }, item.status)),
      ),
      h(
        CardContent,
        null,
        h("p", null, `Current classifier: ${item.classifier || "unknown"}. Status: ${item.status || "unknown"}.`),
        h("p", null, `${formatBytes(item.size_bytes)} · Last updated ${relativeTime(item.last_attempted_at)}`),
        oversized
          ? h("p", { className: "hermes-wiki-health-bad" }, "Oversized: this file exceeds the 50MB Phase-1 ingest cap and is not processable yet.")
          : h(
              "div",
              { className: "hermes-wiki-override-row", "aria-label": `Re-classify ${item.filename}` },
              ...classes.map((classifier) =>
                h(
                  Button,
                  {
                    key: classifier,
                    disabled: props.busy || item.classifier === classifier,
                    onClick: () => props.onOverride(item.filename, classifier),
                  },
                  item.classifier === classifier ? `${classifier} ✓` : `Set ${classifier}`,
                ),
              ),
            ),
      ),
    );
  }

  function formatBytes(value: number) {
    if (!Number.isFinite(value) || value <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let amount = value;
    let unit = 0;
    while (amount >= 1024 && unit < units.length - 1) {
      amount /= 1024;
      unit += 1;
    }
    return `${amount.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
  }

  function renderMarkdownBlocks(markdown: string, slug: string, pageId: string) {
    const lines = markdown.split(/\r?\n/);
    const blocks: unknown[] = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }
      const fence = line.match(/^```(.*)$/);
      if (fence) {
        const codeLines: string[] = [];
        index += 1;
        while (index < lines.length && !lines[index].startsWith("```")) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        blocks.push(h("pre", { key: `code-${index}` }, h("code", { className: fence[1] ? `language-${fence[1].trim()}` : undefined }, codeLines.join("\n"))));
        continue;
      }
      const heading = line.match(/^(#{1,4})\s+(.*)$/);
      if (heading) {
        const level = heading[1].length;
        blocks.push(h(`h${level}`, { key: `h-${index}` }, ...renderInline(heading[2], slug, pageId, `h-${index}`)));
        index += 1;
        continue;
      }
      if (/^[-*]\s+/.test(line)) {
        const items: unknown[] = [];
        while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
          const text = lines[index].replace(/^[-*]\s+/, "");
          items.push(h("li", { key: `li-${index}` }, ...renderInline(text, slug, pageId, `li-${index}`)));
          index += 1;
        }
        blocks.push(h("ul", { key: `ul-${index}` }, ...items));
        continue;
      }
      const paragraph: string[] = [];
      while (
        index < lines.length &&
        lines[index].trim() &&
        !/^```/.test(lines[index]) &&
        !/^(#{1,4})\s+/.test(lines[index]) &&
        !/^[-*]\s+/.test(lines[index])
      ) {
        paragraph.push(lines[index]);
        index += 1;
      }
      blocks.push(h("p", { key: `p-${index}` }, ...renderInline(paragraph.join(" "), slug, pageId, `p-${index}`)));
    }
    return blocks;
  }

  function renderInline(text: string, slug: string, pageId: string, keyPrefix: string) {
    const nodes: unknown[] = [];
    const pattern = /(\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`)/g;
    let last = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text))) {
      if (match.index > last) nodes.push(text.slice(last, match.index));
      if (match[4] !== undefined) {
        nodes.push(h("code", { key: `${keyPrefix}-code-${match.index}` }, match[4]));
      } else {
        const label = match[2];
        const target = match[3];
        nodes.push(renderMarkdownLink(label, target, slug, pageId, `${keyPrefix}-link-${match.index}`));
      }
      last = pattern.lastIndex;
    }
    if (last < text.length) nodes.push(text.slice(last));
    return nodes;
  }

  function renderMarkdownLink(label: string, target: string, slug: string, pageId: string, key: string) {
    if (/^(https?:|mailto:|#)/i.test(target)) {
      return h("a", { key, href: target }, label);
    }
    const linkedPageId = resolveRelativePageId(pageId, target);
    const href = pathForPage(slug, linkedPageId);
    return h("a", { key, href, onClick: onNavigate(href) }, label);
  }

  function resolveRelativePageId(currentPageId: string, target: string) {
    const cleanTarget = target.split("#")[0].split("?")[0].replace(/\.md$/i, "");
    const base = currentPageId.split("/").slice(0, -1);
    const rawParts = cleanTarget.startsWith("/") ? cleanTarget.split("/") : base.concat(cleanTarget.split("/"));
    const parts: string[] = [];
    for (const part of rawParts) {
      if (!part || part === ".") continue;
      if (part === "..") parts.pop();
      else parts.push(decodeURIComponent(part));
    }
    return parts.join("/");
  }

  function parseRoute(locationPath: string) {
    const url = new URL(locationPath, window.location.origin);
    const parts = url.pathname.replace(/^\/wikis\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
    if (!parts.length || parts[0] === "*") return { kind: "landing" as const };
    if (parts[0] === "search") {
      return {
        kind: "search" as const,
        query: url.searchParams.get("q") || "",
        scope: url.searchParams.get("wiki") || "",
      };
    }
    const [slug, ...pageParts] = parts;
    if (!pageParts.length) return { kind: "wiki" as const, slug };
    if (pageParts.length === 1 && pageParts[0] === "inbox") return { kind: "inbox" as const, slug };
    if (pageParts.length === 1 && pageParts[0] === "health") return { kind: "health" as const, slug };
    if (pageParts.length === 1 && pageParts[0] === "log") return { kind: "activity" as const, slug };
    return { kind: "page" as const, slug, pageId: pageParts.join("/") };
  }

  function WikiDashboard() {
    const [path, setPath] = useState<string>(window.location.pathname + window.location.search);

    useEffect(() => {
      const onPopState = () => setPath(window.location.pathname + window.location.search);
      window.addEventListener("popstate", onPopState);
      return () => window.removeEventListener("popstate", onPopState);
    }, []);

    useEffect(() => {
      if (window.location.pathname === "/wikis/*") {
        window.history.replaceState({}, "", "/wikis");
        setPath("/wikis");
      }
    }, [path]);

    const route = parseRoute(path);
    if (route.kind === "landing") return h(LandingRoute, { key: "landing" });
    if (route.kind === "search") return h(SearchRoute, { key: `search-${route.query}-${route.scope}`, query: route.query, scope: route.scope });
    if (route.kind === "wiki") return h(WikiRoute, { key: `wiki-${route.slug}`, slug: route.slug });
    if (route.kind === "inbox") return h(InboxRoute, { key: `inbox-${route.slug}`, slug: route.slug });
    if (route.kind === "health") return h(HealthRoute, { key: `health-${route.slug}`, slug: route.slug });
    if (route.kind === "activity") return h(ActivityRoute, { key: `activity-${route.slug}`, slug: route.slug });
    return h(PageRoute, { key: `page-${route.slug}-${route.pageId}`, slug: route.slug, pageId: route.pageId });
  }

  window.__HERMES_PLUGINS__.register("wiki", WikiDashboard);
}

export {};
