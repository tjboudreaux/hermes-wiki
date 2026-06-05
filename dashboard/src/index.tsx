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
  updated?: string | null;
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
    if (timeAgo) return timeAgo(value);
    return value;
  }

  function wikiPath(slug: string) {
    return `/wikis/${encodeURIComponent(slug)}`;
  }

  function navigate(event: Event, slug: string) {
    event.preventDefault();
    window.history.pushState({}, "", wikiPath(slug));
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  function LoadingState() {
    return h(
      "div",
      { className: "hermes-wiki-state", role: "status" },
      "Loading Wikis…",
    );
  }

  function EmptyState() {
    return h(
      Card,
      { className: "hermes-wiki-empty" },
      h(CardHeader, null, h(CardTitle, null, "No visible Wikis")),
      h(
        CardContent,
        null,
        "Create a Wiki from the API or CLI to make it appear in this dashboard tab.",
      ),
    );
  }

  function ErrorState(props: { message: string; onRetry: () => void }) {
    return h(
      Card,
      { className: "hermes-wiki-error", role: "alert" },
      h(CardHeader, null, h(CardTitle, null, "Could not load Wikis")),
      h(CardContent, null, h("p", null, props.message), h(Button, { onClick: props.onRetry }, "Retry")),
    );
  }

  function WikiCard(props: { wiki: WikiSummary }) {
    const wiki = props.wiki;
    const score = Number(wiki.health_score || 0);
    return h(
      "a",
      {
        className: "hermes-wiki-card-link",
        href: wikiPath(wiki.slug),
        onClick: (event: Event) => navigate(event, wiki.slug),
      },
      h(
        Card,
        { className: "hermes-wiki-card" },
        h(
          CardHeader,
          { className: "hermes-wiki-card-header" },
          h(CardTitle, null, wiki.slug),
          h(Badge, { className: `hermes-wiki-health hermes-wiki-health-${healthTone(score)}` }, `Health ${score.toFixed(2)}`),
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

  function LandingView(props: { wikis: WikiSummary[]; query: string }) {
    const normalizedQuery = props.query.trim().toLowerCase();
    const filtered = useMemo(
      () =>
        props.wikis.filter((wiki) => {
          if (!normalizedQuery) return true;
          return `${wiki.slug} ${wiki.domain || ""}`.toLowerCase().includes(normalizedQuery);
        }),
      [props.wikis, normalizedQuery],
    );

    return h(
      "main",
      { className: "hermes-wiki" },
      h(
        "header",
        { className: "hermes-wiki-hero" },
        h("div", null, h("p", { className: "hermes-wiki-eyebrow" }, "Hermes Wiki"), h("h1", null, "Wikis")),
        h(Badge, null, `${props.wikis.length} visible`),
      ),
      filtered.length
        ? h("section", { className: "hermes-wiki-grid" }, ...filtered.map((wiki) => h(WikiCard, { key: wiki.slug, wiki })))
        : h(EmptyState),
    );
  }

  function WikiPlaceholder(props: { slug: string }) {
    return h(
      "main",
      { className: "hermes-wiki" },
      h("a", { className: "hermes-wiki-back", href: "/wikis" }, "← All Wikis"),
      h(
        Card,
        null,
        h(CardHeader, null, h(CardTitle, null, props.slug)),
        h(
          CardContent,
          null,
          "The backend API for this Wiki is mounted. Detailed Wiki/Page views are implemented in the follow-up dashboard feature.",
        ),
      ),
    );
  }

  function WikiDashboard() {
    const [wikis, setWikis] = useState<WikiSummary[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string>("");
    const [query, setQuery] = useState<string>("");
    const [path, setPath] = useState<string>(window.location.pathname);

    const load = useCallback(() => {
      setLoading(true);
      setError("");
      SDK.fetchJSON<WikiSummary[]>("/api/plugins/wiki/wikis")
        .then((rows) => setWikis(Array.isArray(rows) ? rows : []))
        .catch((err) => setError(err instanceof Error ? err.message : String(err)))
        .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
      load();
    }, [load]);

    useEffect(() => {
      const onPopState = () => setPath(window.location.pathname);
      window.addEventListener("popstate", onPopState);
      return () => window.removeEventListener("popstate", onPopState);
    }, []);

    const slug = path.replace(/^\/wikis\/?/, "").split("/")[0];
    if (slug) {
      return h(WikiPlaceholder, { slug: decodeURIComponent(slug) });
    }
    if (loading) return h(LoadingState);
    if (error) return h(ErrorState, { message: error, onRetry: load });
    return h(
      "div",
      null,
      h(
        "div",
        { className: "hermes-wiki-toolbar" },
        h(Input, {
          "aria-label": "Filter Wikis",
          placeholder: "Filter Wikis…",
          value: query,
          onChange: (event: Event) => setQuery((event.target as HTMLInputElement).value),
        }),
      ),
      h(LandingView, { wikis, query }),
    );
  }

  window.__HERMES_PLUGINS__.register("wiki", WikiDashboard);
}

export {};
