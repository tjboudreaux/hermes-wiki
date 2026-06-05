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
      if (timeAgo) {
        const rendered = timeAgo(value);
        if (rendered && !/NaN/i.test(rendered)) return rendered;
      }
      return value;
    }, formatScore = function(score) {
      return Number(score || 0).toFixed(2);
    }, pathForWiki = function(slug) {
      return `/wikis/${encodeURIComponent(slug)}`;
    }, pathForPage = function(slug, pageId) {
      return `${pathForWiki(slug)}/${encodePageId(pageId)}`;
    }, encodePageId = function(pageId) {
      return pageId.split("/").filter(Boolean).map((part) => encodeURIComponent(part)).join("/");
    }, navigatePath = function(path) {
      window.history.pushState({}, "", path);
      window.dispatchEvent(new Event("popstate"));
    }, onNavigate = function(path) {
      return (event) => {
        event.preventDefault();
        navigatePath(path);
      };
    }, messageOf = function(error) {
      return error instanceof Error ? error.message : String(error);
    }, isNotFound = function(message) {
      return /404|not found|not visible/i.test(message);
    }, LoadingState = function(props) {
      return h("div", { className: "hermes-wiki-state", role: "status" }, props.label);
    }, EmptyState = function(props) {
      return h(
        Card,
        { className: "hermes-wiki-empty" },
        h(CardHeader, null, h(CardTitle, null, props.title)),
        h(CardContent, null, props.body)
      );
    }, ErrorState = function(props) {
      return h(
        Card,
        { className: "hermes-wiki-error", role: "alert" },
        h(CardHeader, null, h(CardTitle, null, props.title)),
        h(
          CardContent,
          null,
          h("p", null, props.message),
          props.onRetry ? h(Button, { onClick: props.onRetry }, "Retry") : null
        )
      );
    }, BackLink = function(props) {
      return h("a", { className: "hermes-wiki-back", href: props.href, onClick: onNavigate(props.href) }, props.label);
    }, WikiCard = function(props) {
      const wiki = props.wiki;
      const score = Number(wiki.health_score || 0);
      return h(
        "a",
        {
          className: "hermes-wiki-card-link",
          href: pathForWiki(wiki.slug),
          onClick: onNavigate(pathForWiki(wiki.slug)),
          "data-wiki-card": wiki.slug
        },
        h(
          Card,
          { className: "hermes-wiki-card" },
          h(
            CardHeader,
            { className: "hermes-wiki-card-header" },
            h(CardTitle, null, wiki.slug),
            h(Badge, { className: `hermes-wiki-health hermes-wiki-health-${healthTone(score)}` }, `Health ${formatScore(score)}`)
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
    }, LandingRoute = function() {
      const [wikis, setWikis] = useState([]);
      const [loading, setLoading] = useState(true);
      const [error, setError] = useState("");
      const [query, setQuery] = useState("");
      const load = useCallback(() => {
        setLoading(true);
        setError("");
        SDK.fetchJSON("/api/plugins/wiki/wikis").then((rows) => setWikis(Array.isArray(rows) ? rows : [])).catch((err) => setError(messageOf(err))).finally(() => setLoading(false));
      }, []);
      useEffect(() => {
        load();
      }, [load]);
      const normalizedQuery = query.trim().toLowerCase();
      const filtered = useMemo(
        () => wikis.filter((wiki) => {
          if (!normalizedQuery) return true;
          return `${wiki.slug} ${wiki.domain || ""}`.toLowerCase().includes(normalizedQuery);
        }),
        [wikis, normalizedQuery]
      );
      if (loading) return h(LoadingState, { label: "Loading Wikis\u2026" });
      if (error) return h(ErrorState, { title: "Could not load Wikis", message: error, onRetry: load });
      return h(
        "main",
        { className: "hermes-wiki" },
        h(
          "header",
          { className: "hermes-wiki-hero" },
          h("div", null, h("p", { className: "hermes-wiki-eyebrow" }, "Hermes Wiki"), h("h1", null, "Wikis")),
          h(Badge, null, `${wikis.length} visible`)
        ),
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
        filtered.length ? h("section", { className: "hermes-wiki-grid" }, ...filtered.map((wiki) => h(WikiCard, { key: wiki.slug, wiki }))) : h(EmptyState, {
          title: wikis.length ? "No Wikis match that filter" : "No visible Wikis",
          body: wikis.length ? "Clear the filter to restore the full visible Wiki list." : "Create a Wiki from the API or CLI to make it appear in this dashboard tab."
        })
      );
    }, WikiRoute = function(props) {
      const [summary, setSummary] = useState(null);
      const [pages, setPages] = useState(null);
      const [allPages, setAllPages] = useState([]);
      const [activity, setActivity] = useState([]);
      const [health, setHealth] = useState(null);
      const [loading, setLoading] = useState(true);
      const [error, setError] = useState("");
      const [pageNumber, setPageNumber] = useState(1);
      const [typeFilter, setTypeFilter] = useState("");
      const [tagFilter, setTagFilter] = useState("");
      const load = useCallback(() => {
        setLoading(true);
        setError("");
        Promise.all([
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}`),
          SDK.fetchJSON(pageListUrl(props.slug, pageNumber, typeFilter, tagFilter)),
          SDK.fetchJSON(pageListUrl(props.slug, 1, "", "", 200)),
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/log?page_size=5`),
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/health`)
        ]).then(([wikiRow, pageRows, allRows, logRows, healthRows]) => {
          setSummary(wikiRow);
          setPages(pageRows);
          setAllPages(allRows.items || []);
          setActivity(logRows.items || []);
          setHealth(healthRows);
        }).catch((err) => setError(messageOf(err))).finally(() => setLoading(false));
      }, [props.slug, pageNumber, typeFilter, tagFilter]);
      useEffect(() => {
        load();
      }, [load]);
      const typeOptions = useMemo(() => sortedUnique(allPages.map((page) => page.type || "").filter(Boolean)), [allPages]);
      const tagOptions = useMemo(
        () => sortedUnique(allPages.flatMap((page) => page.tags || []).filter(Boolean)),
        [allPages]
      );
      if (loading) return h(LoadingState, { label: "Loading Wiki\u2026" });
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
        h(BackLink, { href: "/wikis", label: "\u2190 All Wikis" }),
        h(
          "header",
          { className: "hermes-wiki-detail-hero" },
          h(
            "div",
            null,
            h("p", { className: "hermes-wiki-eyebrow" }, "Wiki"),
            h("h1", null, summary.slug),
            h("p", { className: "hermes-wiki-domain" }, summary.domain || "No domain set")
          ),
          h(
            "div",
            { className: "hermes-wiki-health-panel" },
            h(Badge, { className: `hermes-wiki-health hermes-wiki-health-${healthTone(score)}` }, `Health ${formatScore(score)}`),
            h("span", null, `${summary.page_count} pages`),
            h("span", null, `Last ingest ${relativeTime(summary.last_ingest)}`)
          )
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
              h(Badge, null, `${pages.pagination.total} total`)
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
                      onChange: (event) => {
                        setTypeFilter(event.target.value);
                        setPageNumber(1);
                      }
                    },
                    h("option", { value: "" }, "All types"),
                    ...typeOptions.map((type) => h("option", { key: type, value: type }, type))
                  )
                ),
                h(
                  "label",
                  null,
                  "Tag",
                  h(
                    "select",
                    {
                      value: tagFilter,
                      onChange: (event) => {
                        setTagFilter(event.target.value);
                        setPageNumber(1);
                      }
                    },
                    h("option", { value: "" }, "All tags"),
                    ...tagOptions.map((tag) => h("option", { key: tag, value: tag }, tag))
                  )
                ),
                h(
                  Button,
                  {
                    disabled: !canReset,
                    onClick: () => {
                      setTypeFilter("");
                      setTagFilter("");
                      setPageNumber(1);
                    }
                  },
                  "Reset filters"
                )
              ),
              pages.items.length ? h("div", { className: "hermes-wiki-page-list" }, ...pages.items.map((page) => h(PageListRow, { key: page.id, slug: props.slug, page }))) : h(EmptyState, { title: "No pages found", body: "No pages match the current filters." }),
              h(PaginationControls, { pagination: pages.pagination, onPage: setPageNumber })
            )
          ),
          h(
            "aside",
            { className: "hermes-wiki-side-stack" },
            h(HealthCard, { score, health }),
            h(ActivityTimeline, { entries: activity })
          )
        )
      );
    }, pageListUrl = function(slug, page, typeFilter, tagFilter, pageSize = 5) {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (typeFilter) params.set("type", typeFilter);
      if (tagFilter) params.set("tag", tagFilter);
      return `/api/plugins/wiki/wikis/${encodeURIComponent(slug)}/pages?${params.toString()}`;
    }, sortedUnique = function(values) {
      return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b));
    }, PageListRow = function(props) {
      const page = props.page;
      return h(
        "a",
        {
          className: "hermes-wiki-page-row",
          href: pathForPage(props.slug, page.id),
          onClick: onNavigate(pathForPage(props.slug, page.id)),
          "data-page-id": page.id
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
            ...(page.tags || []).map((tag) => h(Badge, { key: tag }, tag))
          )
        ),
        h("span", { className: "hermes-wiki-muted" }, relativeTime(page.updated))
      );
    }, PaginationControls = function(props) {
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
        h(Button, { disabled: !pagination.has_next, onClick: () => props.onPage(pagination.page + 1) }, "Next")
      );
    }, HealthCard = function(props) {
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
          severities.length ? h("ul", null, ...severities.map(([severity, count]) => h("li", { key: severity }, `${severity}: ${count}`))) : h("p", null, "No lint findings reported.")
        )
      );
    }, ActivityTimeline = function(props) {
      return h(
        Card,
        null,
        h(CardHeader, null, h(CardTitle, null, "Recent Activity")),
        h(
          CardContent,
          null,
          props.entries.length ? h(
            "ol",
            { className: "hermes-wiki-timeline" },
            ...props.entries.map(
              (entry, index) => h(
                "li",
                { key: `${entry.timestamp || entry.created || "entry"}-${index}` },
                h("strong", null, entry.action || "change"),
                h("span", null, entry.target || entry.page_id || "wiki"),
                h("small", null, `${entry.author || "unknown"} \xB7 ${entry.author_kind || "unknown"} \xB7 ${relativeTime(entry.timestamp || entry.created)}`)
              )
            )
          ) : h("p", null, "No activity recorded yet.")
        )
      );
    }, PageRoute = function(props) {
      const [page, setPage] = useState(null);
      const [loading, setLoading] = useState(true);
      const [error, setError] = useState("");
      const load = useCallback(() => {
        setLoading(true);
        setError("");
        SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/pages/${encodePageId(props.pageId)}`).then((row) => setPage(row)).catch((err) => setError(messageOf(err))).finally(() => setLoading(false));
      }, [props.slug, props.pageId]);
      useEffect(() => {
        load();
      }, [load]);
      if (loading) return h(LoadingState, { label: "Loading Page\u2026" });
      if (error) {
        if (isNotFound(error)) {
          return h(
            "main",
            { className: "hermes-wiki" },
            h(BackLink, { href: pathForWiki(props.slug), label: "\u2190 Back to Wiki" }),
            h(ErrorState, { title: "Page not found", message: "This page was not found or is not visible." })
          );
        }
        return h(ErrorState, { title: "Failed to load Page", message: error, onRetry: load });
      }
      if (!page) return h(EmptyState, { title: "Page unavailable", body: "No page data was returned." });
      return h(
        "main",
        { className: "hermes-wiki" },
        h(BackLink, { href: pathForWiki(props.slug), label: "\u2190 Back to Wiki" }),
        h(
          "header",
          { className: "hermes-wiki-detail-hero" },
          h(
            "div",
            null,
            h("p", { className: "hermes-wiki-eyebrow" }, page.type || "Wiki Page"),
            h("h1", null, page.title || page.id),
            h("p", { className: "hermes-wiki-muted" }, page.id)
          ),
          h(Badge, null, page.frontmatter?.confidence ? `Confidence ${String(page.frontmatter.confidence)}` : page.type || "page")
        ),
        h(
          "section",
          { className: "hermes-wiki-page-layout" },
          h(
            "article",
            { className: "hermes-wiki-page-body", "data-testid": "wiki-page-body" },
            h(MarkdownBody, { markdown: page.body || page.markdown || "", slug: props.slug, pageId: page.id })
          ),
          h(
            "aside",
            { className: "hermes-wiki-page-sidebar" },
            h(FrontmatterPanel, { frontmatter: page.frontmatter }),
            h(LinkPanel, { title: "Outbound Links", slug: props.slug, links: page.outbound_pages || refsFromIds(page.outbound_links) }),
            h(LinkPanel, { title: "Inbound Links", slug: props.slug, links: page.inbound_pages || [] }),
            h(KanbanPanel, { refs: page.kanban_refs || [] }),
            h(HistoryPanel, { entries: page.history || [] })
          )
        )
      );
    }, refsFromIds = function(ids) {
      return ids.map((id) => ({ id, title: id, exists: true }));
    }, FrontmatterPanel = function(props) {
      const preferred = ["title", "type", "tags", "confidence", "sources", "author", "author_kind", "created", "updated"];
      const keys = preferred.filter((key) => props.frontmatter[key] !== void 0 && props.frontmatter[key] !== null);
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
            ...keys.flatMap((key) => [h("dt", { key: `${key}-dt` }, key), h("dd", { key: `${key}-dd` }, formatMetadata(props.frontmatter[key]))])
          )
        )
      );
    }, formatMetadata = function(value) {
      if (Array.isArray(value)) return value.join(", ");
      if (typeof value === "object" && value !== null) return JSON.stringify(value);
      return String(value);
    }, LinkPanel = function(props) {
      return h(
        Card,
        null,
        h(CardHeader, null, h(CardTitle, null, props.title)),
        h(
          CardContent,
          null,
          props.links.length ? h(
            "ul",
            { className: "hermes-wiki-link-list" },
            ...props.links.map(
              (link) => h(
                "li",
                { key: link.id },
                h(
                  "a",
                  { href: pathForPage(props.slug, link.id), onClick: onNavigate(pathForPage(props.slug, link.id)) },
                  link.title || link.id
                ),
                link.type ? h(Badge, null, link.type) : null,
                link.exists === false ? h(Badge, { className: "hermes-wiki-health-bad" }, "missing") : null
              )
            )
          ) : h("p", null, "None")
        )
      );
    }, KanbanPanel = function(props) {
      return h(
        Card,
        null,
        h(CardHeader, null, h(CardTitle, null, "Linked Kanban Tasks")),
        h(
          CardContent,
          null,
          props.refs.length ? h(
            "ul",
            { className: "hermes-wiki-link-list" },
            ...props.refs.map(
              (ref, index) => h("li", { key: `${ref.task_id || "task"}-${index}` }, h("strong", null, ref.task_id || "task"), h("span", null, ref.title || ref.direction || "linked"))
            )
          ) : h("p", null, "No linked kanban tasks.")
        )
      );
    }, HistoryPanel = function(props) {
      return h(
        Card,
        { className: "hermes-wiki-history", "data-testid": "wiki-page-history" },
        h(CardHeader, null, h(CardTitle, null, "Page History")),
        h(
          CardContent,
          null,
          props.entries.length ? h(
            "ol",
            { className: "hermes-wiki-timeline" },
            ...props.entries.map(
              (entry, index) => h(
                "li",
                { key: `${entry.timestamp || entry.created || "history"}-${index}` },
                h("strong", null, entry.action || "change"),
                h("span", null, entry.target || entry.page_id || "page"),
                h("small", null, `${entry.author || "unknown"} \xB7 ${entry.author_kind || "unknown"} \xB7 ${relativeTime(entry.timestamp || entry.created)}`)
              )
            )
          ) : h("p", null, "No page history recorded.")
        )
      );
    }, MarkdownBody = function(props) {
      return h("div", { className: "hermes-wiki-markdown" }, ...renderMarkdownBlocks(props.markdown, props.slug, props.pageId));
    }, renderMarkdownBlocks = function(markdown, slug, pageId) {
      const lines = markdown.split(/\r?\n/);
      const blocks = [];
      let index = 0;
      while (index < lines.length) {
        const line = lines[index];
        if (!line.trim()) {
          index += 1;
          continue;
        }
        const fence = line.match(/^```(.*)$/);
        if (fence) {
          const codeLines = [];
          index += 1;
          while (index < lines.length && !lines[index].startsWith("```")) {
            codeLines.push(lines[index]);
            index += 1;
          }
          if (index < lines.length) index += 1;
          blocks.push(h("pre", { key: `code-${index}` }, h("code", { className: fence[1] ? `language-${fence[1].trim()}` : void 0 }, codeLines.join("\n"))));
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
          const items = [];
          while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
            const text = lines[index].replace(/^[-*]\s+/, "");
            items.push(h("li", { key: `li-${index}` }, ...renderInline(text, slug, pageId, `li-${index}`)));
            index += 1;
          }
          blocks.push(h("ul", { key: `ul-${index}` }, ...items));
          continue;
        }
        const paragraph = [];
        while (index < lines.length && lines[index].trim() && !/^```/.test(lines[index]) && !/^(#{1,4})\s+/.test(lines[index]) && !/^[-*]\s+/.test(lines[index])) {
          paragraph.push(lines[index]);
          index += 1;
        }
        blocks.push(h("p", { key: `p-${index}` }, ...renderInline(paragraph.join(" "), slug, pageId, `p-${index}`)));
      }
      return blocks;
    }, renderInline = function(text, slug, pageId, keyPrefix) {
      const nodes = [];
      const pattern = /(\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`)/g;
      let last = 0;
      let match;
      while (match = pattern.exec(text)) {
        if (match.index > last) nodes.push(text.slice(last, match.index));
        if (match[4] !== void 0) {
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
    }, renderMarkdownLink = function(label, target, slug, pageId, key) {
      if (/^(https?:|mailto:|#)/i.test(target)) {
        return h("a", { key, href: target }, label);
      }
      const linkedPageId = resolveRelativePageId(pageId, target);
      const href = pathForPage(slug, linkedPageId);
      return h("a", { key, href, onClick: onNavigate(href) }, label);
    }, resolveRelativePageId = function(currentPageId, target) {
      const cleanTarget = target.split("#")[0].split("?")[0].replace(/\.md$/i, "");
      const base = currentPageId.split("/").slice(0, -1);
      const rawParts = cleanTarget.startsWith("/") ? cleanTarget.split("/") : base.concat(cleanTarget.split("/"));
      const parts = [];
      for (const part of rawParts) {
        if (!part || part === ".") continue;
        if (part === "..") parts.pop();
        else parts.push(decodeURIComponent(part));
      }
      return parts.join("/");
    }, parseRoute = function(pathname) {
      const parts = pathname.replace(/^\/wikis\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
      if (!parts.length || parts[0] === "*") return { kind: "landing" };
      const [slug, ...pageParts] = parts;
      if (!pageParts.length) return { kind: "wiki", slug };
      return { kind: "page", slug, pageId: pageParts.join("/") };
    }, WikiDashboard = function() {
      const [path, setPath] = useState(window.location.pathname);
      useEffect(() => {
        const onPopState = () => setPath(window.location.pathname);
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
      if (route.kind === "wiki") return h(WikiRoute, { key: `wiki-${route.slug}`, slug: route.slug });
      return h(PageRoute, { key: `page-${route.slug}-${route.pageId}`, slug: route.slug, pageId: route.pageId });
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
