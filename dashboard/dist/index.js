(() => {
  // src/index.tsx
  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (SDK && window.__HERMES_PLUGINS__) {
    let healthTone = function(score) {
      if (score >= 0.9) return "good";
      if (score >= 0.7) return "warn";
      return "bad";
    }, relativeTime = function(value) {
      if (!value) return "never";
      if (timeAgo) return timeAgo(value);
      return value;
    }, wikiPath = function(slug) {
      return `/wikis/${encodeURIComponent(slug)}`;
    }, navigate = function(event, slug) {
      event.preventDefault();
      window.history.pushState({}, "", wikiPath(slug));
      window.dispatchEvent(new PopStateEvent("popstate"));
    }, LoadingState = function() {
      return h(
        "div",
        { className: "hermes-wiki-state", role: "status" },
        "Loading Wikis\u2026"
      );
    }, EmptyState = function() {
      return h(
        Card,
        { className: "hermes-wiki-empty" },
        h(CardHeader, null, h(CardTitle, null, "No visible Wikis")),
        h(
          CardContent,
          null,
          "Create a Wiki from the API or CLI to make it appear in this dashboard tab."
        )
      );
    }, ErrorState = function(props) {
      return h(
        Card,
        { className: "hermes-wiki-error", role: "alert" },
        h(CardHeader, null, h(CardTitle, null, "Could not load Wikis")),
        h(CardContent, null, h("p", null, props.message), h(Button, { onClick: props.onRetry }, "Retry"))
      );
    }, WikiCard = function(props) {
      const wiki = props.wiki;
      const score = Number(wiki.health_score || 0);
      return h(
        "a",
        {
          className: "hermes-wiki-card-link",
          href: wikiPath(wiki.slug),
          onClick: (event) => navigate(event, wiki.slug)
        },
        h(
          Card,
          { className: "hermes-wiki-card" },
          h(
            CardHeader,
            { className: "hermes-wiki-card-header" },
            h(CardTitle, null, wiki.slug),
            h(Badge, { className: `hermes-wiki-health hermes-wiki-health-${healthTone(score)}` }, `Health ${score.toFixed(2)}`)
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
              h("div", null, h("dt", null, "Last ingest"), h("dd", null, relativeTime(wiki.last_ingest)))
            )
          )
        )
      );
    }, LandingView = function(props) {
      const normalizedQuery = props.query.trim().toLowerCase();
      const filtered = useMemo(
        () => props.wikis.filter((wiki) => {
          if (!normalizedQuery) return true;
          return `${wiki.slug} ${wiki.domain || ""}`.toLowerCase().includes(normalizedQuery);
        }),
        [props.wikis, normalizedQuery]
      );
      return h(
        "main",
        { className: "hermes-wiki" },
        h(
          "header",
          { className: "hermes-wiki-hero" },
          h("div", null, h("p", { className: "hermes-wiki-eyebrow" }, "Hermes Wiki"), h("h1", null, "Wikis")),
          h(Badge, null, `${props.wikis.length} visible`)
        ),
        filtered.length ? h("section", { className: "hermes-wiki-grid" }, ...filtered.map((wiki) => h(WikiCard, { key: wiki.slug, wiki }))) : h(EmptyState)
      );
    }, WikiPlaceholder = function(props) {
      return h(
        "main",
        { className: "hermes-wiki" },
        h("a", { className: "hermes-wiki-back", href: "/wikis" }, "\u2190 All Wikis"),
        h(
          Card,
          null,
          h(CardHeader, null, h(CardTitle, null, props.slug)),
          h(
            CardContent,
            null,
            "The backend API for this Wiki is mounted. Detailed Wiki/Page views are implemented in the follow-up dashboard feature."
          )
        )
      );
    }, WikiDashboard = function() {
      const [wikis, setWikis] = useState([]);
      const [loading, setLoading] = useState(true);
      const [error, setError] = useState("");
      const [query, setQuery] = useState("");
      const [path, setPath] = useState(window.location.pathname);
      const load = useCallback(() => {
        setLoading(true);
        setError("");
        SDK.fetchJSON("/api/plugins/wiki/wikis").then((rows) => setWikis(Array.isArray(rows) ? rows : [])).catch((err) => setError(err instanceof Error ? err.message : String(err))).finally(() => setLoading(false));
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
            placeholder: "Filter Wikis\u2026",
            value: query,
            onChange: (event) => setQuery(event.target.value)
          })
        ),
        h(LandingView, { wikis, query })
      );
    };
    const { React } = SDK;
    const h = React.createElement;
    const { useCallback, useEffect, useMemo, useState } = SDK.hooks;
    const components = SDK.components || {};
    const Card = components.Card || "section";
    const CardHeader = components.CardHeader || "div";
    const CardTitle = components.CardTitle || "h3";
    const CardContent = components.CardContent || "div";
    const Badge = components.Badge || "span";
    const Button = components.Button || "button";
    const Input = components.Input || "input";
    const timeAgo = SDK.utils?.timeAgo;
    window.__HERMES_PLUGINS__.register("wiki", WikiDashboard);
  }
})();
