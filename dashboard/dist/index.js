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
    }, pathForInbox = function(slug) {
      return `${pathForWiki(slug)}/inbox`;
    }, pathForInboxFile = function(slug, filename) {
      return `${pathForInbox(slug)}/${encodeURIComponent(filename)}`;
    }, pathForHealth = function(slug) {
      return `${pathForWiki(slug)}/health`;
    }, pathForLog = function(slug) {
      return `${pathForWiki(slug)}/log`;
    }, pathForSearch = function(query = "", wiki = "") {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      if (wiki.trim()) params.set("wiki", wiki.trim());
      const suffix = params.toString();
      return `/wikis/search${suffix ? `?${suffix}` : ""}`;
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
        h(CardContent, null, h("p", null, props.body), props.children || null)
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
      const [createSlug, setCreateSlug] = useState("");
      const [createDomain, setCreateDomain] = useState("");
      const [createError, setCreateError] = useState("");
      const [creating, setCreating] = useState(false);
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
      const createWiki = (event) => {
        event.preventDefault();
        const slug = createSlug.trim();
        const domain = createDomain.trim();
        setCreateError("");
        if (!/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(slug)) {
          setCreateError("Use lowercase letters, digits, and internal hyphens.");
          return;
        }
        setCreating(true);
        SDK.fetchJSON("/api/plugins/wiki/wikis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug, domain: domain || null })
        }).then((created) => {
          setWikis(
            (previous) => sortedWikis(previous.filter((wiki) => wiki.slug !== created.slug).concat(created))
          );
          setCreateSlug("");
          setCreateDomain("");
          navigatePath(pathForWiki(created.slug));
        }).catch((err) => setCreateError(messageOf(err))).finally(() => setCreating(false));
      };
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
        h(CreateWikiForm, {
          slug: createSlug,
          domain: createDomain,
          error: createError,
          creating,
          onSlug: setCreateSlug,
          onDomain: setCreateDomain,
          onSubmit: createWiki
        }),
        h(
          "div",
          { className: "hermes-wiki-toolbar" },
          h("a", { className: "hermes-wiki-action-link", href: pathForSearch(), onClick: onNavigate(pathForSearch()) }, "Global Search"),
          h(Input, {
            "aria-label": "Filter Wikis",
            placeholder: "Filter Wikis\u2026",
            value: query,
            onChange: (event) => setQuery(event.target.value)
          })
        ),
        filtered.length ? h("section", { className: "hermes-wiki-grid" }, ...filtered.map((wiki) => h(WikiCard, { key: wiki.slug, wiki }))) : h(EmptyState, {
          title: wikis.length ? "No Wikis match that filter" : "No visible Wikis",
          body: wikis.length ? "Clear the filter to see the complete list again." : "Create the first Wiki here, then ingest sources from the CLI or inbox.",
          children: wikis.length ? h(Button, { onClick: () => setQuery("") }, "Clear filter") : h("span", { className: "hermes-wiki-muted" }, "Suggested slug: ai-research, product-intel, support-playbooks")
        })
      );
    }, sortedWikis = function(wikis) {
      return wikis.slice().sort((left, right) => left.slug.localeCompare(right.slug));
    }, CreateWikiForm = function(props) {
      return h(
        Card,
        { className: "hermes-wiki-create" },
        h(
          CardHeader,
          { className: "hermes-wiki-card-header" },
          h("div", null, h(CardTitle, null, "Create a Wiki"), h("p", { className: "hermes-wiki-muted" }, "Start a durable knowledge base without leaving the dashboard.")),
          h(Badge, null, "New")
        ),
        h(
          CardContent,
          null,
          h(
            "form",
            { className: "hermes-wiki-create-form", onSubmit: props.onSubmit },
            h(
              "label",
              null,
              "Slug",
              h(Input, {
                "aria-label": "Wiki slug",
                placeholder: "ai-research",
                value: props.slug,
                pattern: "[a-z0-9](?:[a-z0-9-]*[a-z0-9])?",
                onChange: (event) => props.onSlug(event.target.value)
              })
            ),
            h(
              "label",
              null,
              "Domain",
              h(Input, {
                "aria-label": "Wiki domain",
                placeholder: "AI research papers and implementation notes",
                value: props.domain,
                onChange: (event) => props.onDomain(event.target.value)
              })
            ),
            h(Button, { type: "submit", disabled: props.creating }, props.creating ? "Creating\u2026" : "Create Wiki")
          ),
          props.error ? h("p", { className: "hermes-wiki-health-bad" }, props.error) : null
        )
      );
    }, WikiRoute = function(props) {
      const [summary, setSummary] = useState(null);
      const [pages, setPages] = useState(null);
      const [facets, setFacets] = useState(null);
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
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/pages/facets`),
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/log?page_size=5`),
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/health`)
        ]).then(([wikiRow, pageRows, facetRows, logRows, healthRows]) => {
          setSummary(wikiRow);
          setPages(pageRows);
          setFacets(facetRows);
          setActivity(logRows.items || []);
          setHealth(healthRows);
        }).catch((err) => setError(messageOf(err))).finally(() => setLoading(false));
      }, [props.slug, pageNumber, typeFilter, tagFilter]);
      useEffect(() => {
        load();
      }, [load]);
      const typeOptions = useMemo(() => sortedUnique(facets?.types || []), [facets]);
      const tagOptions = useMemo(() => sortedUnique(facets?.tags || []), [facets]);
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
            h("a", { className: "hermes-wiki-action-link", href: pathForSearch("", summary.slug), onClick: onNavigate(pathForSearch("", summary.slug)) }, "Search this Wiki"),
            h("a", { className: "hermes-wiki-action-link", href: pathForInbox(summary.slug), onClick: onNavigate(pathForInbox(summary.slug)) }, "Inbox"),
            h("a", { className: "hermes-wiki-action-link", href: pathForHealth(summary.slug), onClick: onNavigate(pathForHealth(summary.slug)) }, "Health"),
            h("a", { className: "hermes-wiki-action-link", href: pathForLog(summary.slug), onClick: onNavigate(pathForLog(summary.slug)) }, "Activity"),
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
              pages.items.length ? h("div", { className: "hermes-wiki-page-list" }, ...pages.items.map((page) => h(PageListRow, { key: page.id, slug: props.slug, page }))) : h(EmptyState, {
                title: canReset ? "No pages match those filters" : "No pages yet",
                body: canReset ? "Reset filters to see the full page list." : "Ingest a source or process the inbox to create the first curated Wiki Page.",
                children: canReset ? h(Button, {
                  onClick: () => {
                    setTypeFilter("");
                    setTagFilter("");
                    setPageNumber(1);
                  }
                }, "Reset filters") : h(
                  "div",
                  { className: "hermes-wiki-empty-actions" },
                  h("a", { className: "hermes-wiki-action-link", href: pathForInbox(props.slug), onClick: onNavigate(pathForInbox(props.slug)) }, "Open Inbox"),
                  h("a", { className: "hermes-wiki-action-link", href: pathForSearch("", props.slug), onClick: onNavigate(pathForSearch("", props.slug)) }, "Search this Wiki")
                )
              }),
              h(PaginationControls, { pagination: pages.pagination, onPage: setPageNumber })
            )
          ),
          h(
            "aside",
            { className: "hermes-wiki-side-stack" },
            h(HealthCard, { score, health, slug: summary.slug }),
            h(SkillsCard, { slug: summary.slug }),
            h(ActivityTimeline, { entries: activity, slug: summary.slug })
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
    }, SkillsCard = function(props) {
      const [skills, setSkills] = useState(null);
      const [ingestion, setIngestion] = useState("");
      const [writing, setWriting] = useState("");
      const [error, setError] = useState("");
      const [notice, setNotice] = useState("");
      const [saving, setSaving] = useState(false);
      const skillsUrl = `/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/skills`;
      const load = useCallback(() => {
        setError("");
        SDK.fetchJSON(skillsUrl).then((row) => {
          setSkills(row);
          setIngestion(row.skills.ingestion || "");
          setWriting(row.skills.writing || "");
        }).catch((err) => setError(messageOf(err)));
      }, [props.slug]);
      useEffect(() => {
        load();
      }, [load]);
      const dirty = skills ? ingestion !== skills.skills.ingestion || writing !== skills.skills.writing : false;
      const save = () => {
        if (!skills) return;
        const payload = {};
        if (ingestion !== skills.skills.ingestion) payload.ingestion = ingestion.trim();
        if (writing !== skills.skills.writing) payload.writing = writing.trim();
        setSaving(true);
        setError("");
        setNotice("");
        SDK.fetchJSON(skillsUrl, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        }).then((row) => {
          setSkills(row);
          setIngestion(row.skills.ingestion || "");
          setWriting(row.skills.writing || "");
          setNotice("Skills saved.");
        }).catch((err) => setError(messageOf(err))).finally(() => setSaving(false));
      };
      const renderField = (label, value, fallback, onChange) => h(
        "label",
        { className: "hermes-wiki-skill-field" },
        label,
        h(Input, {
          value,
          placeholder: fallback,
          disabled: !skills || saving,
          onChange: (event) => onChange(event.target.value)
        }),
        value && value === fallback ? h("span", { className: "hermes-wiki-muted" }, "default") : null
      );
      return h(
        Card,
        { className: "hermes-wiki-skills-card" },
        h(
          CardHeader,
          { className: "hermes-wiki-card-header" },
          h(CardTitle, null, "Skills"),
          h(Badge, null, "per-wiki")
        ),
        h(
          CardContent,
          null,
          h("p", { className: "hermes-wiki-muted" }, "Skills that guide agents ingesting into and writing for this Wiki."),
          renderField("Ingestion", ingestion, skills?.defaults.ingestion || "", setIngestion),
          renderField("Writing", writing, skills?.defaults.writing || "", setWriting),
          error ? h("p", { className: "hermes-wiki-health-bad", role: "alert" }, error) : null,
          notice ? h("p", { className: "hermes-wiki-health-good" }, notice) : null,
          h(
            "div",
            { className: "hermes-wiki-skill-actions" },
            h(Button, { disabled: !dirty || saving || !ingestion.trim() || !writing.trim(), onClick: save }, saving ? "Saving\u2026" : "Save")
          )
        )
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
          severities.length ? h("ul", null, ...severities.map(([severity, count]) => h("li", { key: severity }, `${severity}: ${count}`))) : h("p", null, "No lint findings. The projection and page metadata are in sync."),
          props.slug ? h("a", { className: "hermes-wiki-action-link", href: pathForHealth(props.slug), onClick: onNavigate(pathForHealth(props.slug)) }, "Open Health") : null
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
          ) : h("p", null, "No activity yet. Creates, ingests, links, and lint repairs appear here."),
          props.slug ? h("a", { className: "hermes-wiki-action-link", href: pathForLog(props.slug), onClick: onNavigate(pathForLog(props.slug)) }, "Open Activity") : null
        )
      );
    }, severityLabel = function(severity) {
      const value = (severity || "low").toLowerCase();
      if (value === "high") return "\u{1F534} high";
      if (value === "medium") return "\u26A0\uFE0F medium";
      return "\u{1F4A1} low";
    }, severityClass = function(severity) {
      const value = (severity || "low").toLowerCase();
      if (value === "high") return "hermes-wiki-health-bad";
      if (value === "medium") return "hermes-wiki-health-warn";
      return "hermes-wiki-health-good";
    }, HealthRoute = function(props) {
      const [summary, setSummary] = useState(null);
      const [report, setReport] = useState(null);
      const [selectedSeverities, setSelectedSeverities] = useState([]);
      const [loading, setLoading] = useState(true);
      const [error, setError] = useState("");
      const load = useCallback(() => {
        setLoading(true);
        setError("");
        Promise.all([
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}`),
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/health`)
        ]).then(([wikiRow, healthRows]) => {
          setSummary(wikiRow);
          setReport(healthRows);
        }).catch((err) => setError(messageOf(err))).finally(() => setLoading(false));
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
      const toggleSeverity = (severity) => {
        setSelectedSeverities(
          (previous) => previous.includes(severity) ? previous.filter((item) => item !== severity) : previous.concat(severity)
        );
      };
      if (loading) return h(LoadingState, { label: "Loading Health\u2026" });
      if (error) {
        if (isNotFound(error)) {
          return h(
            "main",
            { className: "hermes-wiki" },
            h(BackLink, { href: pathForWiki(props.slug), label: "\u2190 Back to Wiki" }),
            h(ErrorState, { title: "Health report not found", message: "This Wiki health report was not found or is not visible." })
          );
        }
        return h(ErrorState, { title: "Failed to load Health", message: error, onRetry: load });
      }
      const score = Number(report?.health_score ?? summary?.health_score ?? 0);
      const allSelected = selectedSeverities.length === 0;
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
            h("p", { className: "hermes-wiki-eyebrow" }, "Wiki Health"),
            h("h1", null, `${summary?.slug || props.slug} Health`),
            h("p", { className: "hermes-wiki-domain" }, "Lint findings and consistency checks")
          ),
          h(
            "div",
            { className: "hermes-wiki-health-panel" },
            h(Badge, { className: `hermes-wiki-health hermes-wiki-health-${healthTone(score)}` }, `Score ${formatScore(score)}`),
            h(Badge, null, `${findings.length} findings`)
          )
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
              ...["high", "medium", "low"].map(
                (severity) => h(
                  "label",
                  { key: severity },
                  h("input", {
                    type: "checkbox",
                    checked: selectedSeverities.includes(severity),
                    onChange: () => toggleSeverity(severity)
                  }),
                  `${severityLabel(severity)} (${Number(counts[severity] || 0)})`
                )
              ),
              h(Button, { disabled: allSelected, onClick: () => setSelectedSeverities([]) }, "Clear severity filters")
            )
          )
        ),
        findings.length === 0 ? h(EmptyState, { title: "Healthy Wiki", body: "No lint findings. Keep ingesting sources and this panel will flag drift, missing links, or projection issues." }) : filteredFindings.length ? h(
          "section",
          { className: "hermes-wiki-finding-list", "data-testid": "wiki-health-findings" },
          ...filteredFindings.map((finding, index) => h(HealthFindingRow, { key: `${finding.check || finding.code || "finding"}-${index}`, finding }))
        ) : h(EmptyState, {
          title: "No findings match those severities",
          body: "Select additional severities or clear filters to restore the full lint report."
        })
      );
    }, HealthFindingRow = function(props) {
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
          h(Badge, { className: severityClass(severity) }, severityLabel(severity))
        ),
        h(
          CardContent,
          null,
          h("p", null, finding.message || "No finding message was provided."),
          target ? h("p", { className: "hermes-wiki-muted" }, target) : null
        )
      );
    }, ActivityRoute = function(props) {
      const [summary, setSummary] = useState(null);
      const [entries, setEntries] = useState([]);
      const [facets, setFacets] = useState(null);
      const [pagination, setPagination] = useState(null);
      const [authorFilter, setAuthorFilter] = useState("");
      const [kindFilter, setKindFilter] = useState("");
      const [pageNumber, setPageNumber] = useState(1);
      const [loading, setLoading] = useState(true);
      const [error, setError] = useState("");
      const load = useCallback(() => {
        setLoading(true);
        setError("");
        Promise.all([
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}`),
          SDK.fetchJSON(activityUrl(props.slug, pageNumber, authorFilter, kindFilter, 5)),
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/log/facets`)
        ]).then(([wikiRow, logRows, facetRows]) => {
          setSummary(wikiRow);
          setEntries(Array.isArray(logRows.items) ? logRows.items : []);
          setPagination(logRows.pagination);
          setFacets(facetRows);
        }).catch((err) => setError(messageOf(err))).finally(() => setLoading(false));
      }, [props.slug, pageNumber, authorFilter, kindFilter]);
      useEffect(() => {
        load();
      }, [load]);
      const authorOptions = useMemo(() => sortedUnique(facets?.authors || []), [facets]);
      const kindOptions = useMemo(() => sortedUnique(facets?.kinds || []), [facets]);
      if (loading) return h(LoadingState, { label: "Loading Activity\u2026" });
      if (error) {
        if (isNotFound(error)) {
          return h(
            "main",
            { className: "hermes-wiki" },
            h(BackLink, { href: pathForWiki(props.slug), label: "\u2190 Back to Wiki" }),
            h(ErrorState, { title: "Activity log not found", message: "This Wiki activity log was not found or is not visible." })
          );
        }
        return h(ErrorState, { title: "Failed to load Activity", message: error, onRetry: load });
      }
      const canReset = Boolean(authorFilter || kindFilter);
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
            h("p", { className: "hermes-wiki-eyebrow" }, "Wiki Activity"),
            h("h1", null, `${summary?.slug || props.slug} Activity`),
            h("p", { className: "hermes-wiki-domain" }, "Chronological attributed changes")
          ),
          h(Badge, null, `${pagination?.total ?? entries.length} entries`)
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
                    onChange: (event) => {
                      setAuthorFilter(event.target.value);
                      setPageNumber(1);
                    }
                  },
                  h("option", { value: "" }, "All authors"),
                  ...authorOptions.map((author) => h("option", { key: author, value: author }, author))
                )
              ),
              h(
                "label",
                null,
                "Kind",
                h(
                  "select",
                  {
                    value: kindFilter,
                    onChange: (event) => {
                      setKindFilter(event.target.value);
                      setPageNumber(1);
                    }
                  },
                  h("option", { value: "" }, "All kinds"),
                  ...kindOptions.map((kind) => h("option", { key: kind, value: kind }, kind))
                )
              ),
              h(
                Button,
                {
                  disabled: !canReset,
                  onClick: () => {
                    setAuthorFilter("");
                    setKindFilter("");
                    setPageNumber(1);
                  }
                },
                "Reset filters"
              )
            )
          )
        ),
        entries.length ? h(
          "section",
          { className: "hermes-wiki-activity-list", "data-testid": "wiki-activity-log" },
          h(
            "ol",
            { className: "hermes-wiki-timeline" },
            ...entries.map((entry, index) => h(ActivityLogRow, { key: `${entry.timestamp || entry.created || "entry"}-${index}`, entry }))
          ),
          pagination ? h(PaginationControls, { pagination, onPage: setPageNumber }) : null
        ) : h(EmptyState, {
          title: "No activity entries",
          body: canReset ? "No activity entries match the selected filters." : "No activity yet. Wiki creates, ingests, links, and repairs will appear here with attribution.",
          children: canReset ? h(Button, {
            onClick: () => {
              setAuthorFilter("");
              setKindFilter("");
              setPageNumber(1);
            }
          }, "Reset filters") : null
        })
      );
    }, activityUrl = function(slug, page, author, kind, pageSize) {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (author) params.set("author", author);
      if (kind) params.set("kind", kind);
      return `/api/plugins/wiki/wikis/${encodeURIComponent(slug)}/log?${params.toString()}`;
    }, ActivityLogRow = function(props) {
      const entry = props.entry;
      return h(
        "li",
        {
          "data-author": entry.author || "",
          "data-author-kind": entry.author_kind || "",
          "data-timestamp": entry.timestamp || entry.created || ""
        },
        h("strong", null, entry.action || "change"),
        h("span", null, entry.target || entry.page_id || "wiki"),
        h("small", null, `${entry.author || "unknown"} \xB7 ${entry.author_kind || "unknown"} \xB7 ${entry.timestamp || entry.created || "unknown time"}`),
        entry.details ? h("span", { className: "hermes-wiki-muted" }, entry.details) : null
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
    }, SearchRoute = function(props) {
      const [wikis, setWikis] = useState([]);
      const [query, setQuery] = useState(props.query);
      const [scope, setScope] = useState(props.scope);
      const [results, setResults] = useState([]);
      const [loading, setLoading] = useState(false);
      const [error, setError] = useState("");
      useEffect(() => {
        setQuery(props.query);
        setScope(props.scope);
      }, [props.query, props.scope]);
      useEffect(() => {
        SDK.fetchJSON("/api/plugins/wiki/wikis").then((rows) => setWikis(Array.isArray(rows) ? rows : [])).catch(() => setWikis([]));
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
        const url = props.scope ? `/api/plugins/wiki/wikis/${encodeURIComponent(props.scope)}/search?${params.toString()}` : `/api/plugins/wiki/search?${params.toString()}`;
        SDK.fetchJSON(url).then((row) => setResults(Array.isArray(row.results) ? row.results : [])).catch((err) => setError(messageOf(err))).finally(() => setLoading(false));
      }, [props.query, props.scope]);
      useEffect(() => {
        load();
      }, [load]);
      const submit = (event) => {
        event.preventDefault();
        navigatePath(pathForSearch(query, scope));
      };
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
            h("p", { className: "hermes-wiki-eyebrow" }, "Wiki Search"),
            h("h1", null, "Search Wikis"),
            h("p", { className: "hermes-wiki-domain" }, scope ? `Scoped to ${scope}` : "Across all visible Wikis")
          ),
          h(Badge, null, props.query ? `${results.length} results` : "BM25 ranked")
        ),
        h(
          "form",
          { className: "hermes-wiki-search-form", onSubmit: submit },
          h(Input, {
            "aria-label": "Search query",
            placeholder: "Search pages\u2026",
            value: query,
            onChange: (event) => setQuery(event.target.value)
          }),
          h(
            "select",
            {
              "aria-label": "Search scope",
              value: scope,
              onChange: (event) => setScope(event.target.value)
            },
            h("option", { value: "" }, "All visible Wikis"),
            ...wikis.map((wiki) => h("option", { key: wiki.slug, value: wiki.slug }, wiki.slug))
          ),
          h(Button, { type: "submit" }, "Search")
        ),
        loading ? h(LoadingState, { label: "Searching Wikis\u2026" }) : error ? h(ErrorState, { title: "Search failed", message: error, onRetry: load }) : !props.query.trim() ? h(EmptyState, { title: "Search all visible Wikis", body: "Search page titles, body text, tags, and normalized technical terms across visible Wikis." }) : results.length ? h("section", { className: "hermes-wiki-result-list" }, ...results.map((result) => h(SearchResultRow, { key: `${result.wiki}:${result.id}`, result }))) : h(EmptyState, { title: "No results", body: "Try a broader term, remove the Wiki scope, or ingest a source that covers this topic." })
      );
    }, SearchResultRow = function(props) {
      const result = props.result;
      const href = result.href || pathForPage(result.wiki, result.id);
      return h(
        "a",
        {
          className: "hermes-wiki-result-row",
          href,
          onClick: onNavigate(href),
          "data-search-result": `${result.wiki}:${result.id}`
        },
        h(
          Card,
          null,
          h(
            CardHeader,
            { className: "hermes-wiki-card-header" },
            h(CardTitle, null, result.title || result.id),
            h("div", { className: "hermes-wiki-tags" }, h(Badge, null, result.wiki), h(Badge, null, result.type || "page"))
          ),
          h(
            CardContent,
            null,
            h("p", null, result.snippet || result.id),
            h("small", { className: "hermes-wiki-muted" }, `BM25 rank ${Number(result.rank || result.score || 0).toFixed(4)}`)
          )
        )
      );
    }, InboxRoute = function(props) {
      const [summary, setSummary] = useState(null);
      const [items, setItems] = useState([]);
      const [loading, setLoading] = useState(true);
      const [error, setError] = useState("");
      const [busyFile, setBusyFile] = useState("");
      const [busyIngest, setBusyIngest] = useState(false);
      const [notice, setNotice] = useState("");
      const load = useCallback(() => {
        setLoading(true);
        setError("");
        Promise.all([
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}`),
          SDK.fetchJSON(`/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/inbox`)
        ]).then(([wikiRow, inboxRows]) => {
          setSummary(wikiRow);
          setItems(Array.isArray(inboxRows) ? inboxRows : []);
        }).catch((err) => setError(messageOf(err))).finally(() => setLoading(false));
      }, [props.slug]);
      useEffect(() => {
        load();
      }, [load]);
      const overrideClassifier = (filename, classifier) => {
        setBusyFile(filename);
        setError("");
        setNotice("");
        SDK.fetchJSON(
          `/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/inbox/${encodeURIComponent(filename)}/classify`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ classifier })
          }
        ).then((updated) => {
          setItems((previous) => previous.map((item) => item.filename === updated.filename ? updated : item));
        }).catch((err) => setError(messageOf(err))).finally(() => setBusyFile(""));
      };
      const processInbox = () => {
        setBusyIngest(true);
        setError("");
        setNotice("");
        SDK.fetchJSON(
          `/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/ingest`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ inbox: true })
          }
        ).then((result) => {
          const changedPages = (result.results || []).reduce(
            (count, row) => count + (row.pages_created || []).length + (row.pages_updated || []).length,
            0
          );
          setNotice(changedPages ? `Processed inbox and updated ${changedPages} page${changedPages === 1 ? "" : "s"}.` : "Inbox processed; no pages changed.");
          load();
        }).catch((err) => setError(messageOf(err))).finally(() => setBusyIngest(false));
      };
      if (loading) return h(LoadingState, { label: "Loading Inbox\u2026" });
      if (error && !items.length) {
        if (isNotFound(error)) {
          return h(
            "main",
            { className: "hermes-wiki" },
            h(BackLink, { href: pathForWiki(props.slug), label: "\u2190 Back to Wiki" }),
            h(ErrorState, { title: "Inbox not found", message: "This Wiki inbox was not found or is not visible." })
          );
        }
        return h(ErrorState, { title: "Failed to load Inbox", message: error, onRetry: load });
      }
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
            h("p", { className: "hermes-wiki-eyebrow" }, "Wiki Inbox"),
            h("h1", null, `${summary?.slug || props.slug} Inbox`),
            h("p", { className: "hermes-wiki-domain" }, "Unprocessed raw files and classifier assignments")
          ),
          h(
            "div",
            { className: "hermes-wiki-health-panel" },
            h(Badge, null, `${items.length} pending`),
            h(Button, { disabled: !items.length || busyIngest, onClick: processInbox }, busyIngest ? "Processing\u2026" : "Process Inbox")
          )
        ),
        error ? h(ErrorState, { title: "Inbox update failed", message: error, onRetry: load }) : null,
        notice ? h(Card, { className: "hermes-wiki-notice" }, h(CardContent, null, notice)) : null,
        items.length ? h(
          "section",
          { className: "hermes-wiki-inbox-list" },
          ...items.map(
            (item) => h(InboxItemRow, {
              key: item.filename,
              slug: props.slug,
              item,
              busy: busyFile === item.filename,
              onOverride: overrideClassifier
            })
          )
        ) : h(EmptyState, { title: "Inbox is empty", body: "There are no unprocessed files in raw/inbox for this Wiki." })
      );
    }, InboxItemRow = function(props) {
      const item = props.item;
      const oversized = item.status === "oversized" || item.classifier === "oversized";
      const classes = ["article", "paper", "transcript", "unknown"];
      const fileHref = pathForInboxFile(props.slug, item.filename);
      return h(
        Card,
        { className: oversized ? "hermes-wiki-inbox-item hermes-wiki-inbox-oversized" : "hermes-wiki-inbox-item" },
        h(
          CardHeader,
          { className: "hermes-wiki-card-header" },
          h(
            "div",
            null,
            h(
              CardTitle,
              null,
              h("a", { className: "hermes-wiki-inbox-open", href: fileHref, onClick: onNavigate(fileHref) }, item.filename)
            ),
            h("p", { className: "hermes-wiki-muted" }, item.path)
          ),
          h("div", { className: "hermes-wiki-tags" }, h(Badge, null, item.classifier || "unknown"), h(Badge, { className: oversized ? "hermes-wiki-health-bad" : "" }, item.status))
        ),
        h(
          CardContent,
          null,
          h("p", null, `Current classifier: ${item.classifier || "unknown"}. Status: ${item.status || "unknown"}.`),
          h("p", null, `${formatBytes(item.size_bytes)} \xB7 Last updated ${relativeTime(item.last_attempted_at)}`),
          oversized ? h("p", { className: "hermes-wiki-health-bad" }, "Oversized: this file exceeds the 50MB Phase-1 ingest cap and is not processable yet.") : h(
            "div",
            { className: "hermes-wiki-override-row", "aria-label": `Re-classify ${item.filename}` },
            ...classes.map(
              (classifier) => h(
                Button,
                {
                  key: classifier,
                  disabled: props.busy || item.classifier === classifier,
                  onClick: () => props.onOverride(item.filename, classifier)
                },
                item.classifier === classifier ? `${classifier} \u2713` : `Set ${classifier}`
              )
            )
          )
        )
      );
    }, isUnsupportedContent = function(message) {
      return /413|415|too large|not valid|not utf-8|unsupported media/i.test(message);
    }, InboxFileRoute = function(props) {
      const [detail, setDetail] = useState(null);
      const [content, setContent] = useState("");
      const [loading, setLoading] = useState(true);
      const [error, setError] = useState("");
      const [saving, setSaving] = useState(false);
      const [deleting, setDeleting] = useState(false);
      const [notice, setNotice] = useState("");
      const [readOnly, setReadOnly] = useState(false);
      const fileUrl = `/api/plugins/wiki/wikis/${encodeURIComponent(props.slug)}/inbox/${encodeURIComponent(props.filename)}`;
      const load = useCallback(() => {
        setLoading(true);
        setError("");
        setNotice("");
        setReadOnly(false);
        SDK.fetchJSON(fileUrl).then((row) => {
          setDetail(row);
          setContent(row.content || "");
        }).catch((err) => {
          const message = messageOf(err);
          if (isUnsupportedContent(message)) {
            setReadOnly(true);
            setNotice("This file cannot be viewed or edited here (binary or oversized). You can still delete it.");
          } else {
            setError(message);
          }
        }).finally(() => setLoading(false));
      }, [props.slug, props.filename]);
      useEffect(() => {
        load();
      }, [load]);
      const save = () => {
        setSaving(true);
        setError("");
        setNotice("");
        SDK.fetchJSON(fileUrl, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content })
        }).then((row) => {
          setDetail(row);
          setContent(row.content || "");
          setNotice("Saved.");
        }).catch((err) => setError(messageOf(err))).finally(() => setSaving(false));
      };
      const remove = () => {
        if (!window.confirm(`Delete ${props.filename} from the inbox? This cannot be undone.`)) return;
        setDeleting(true);
        setError("");
        setNotice("");
        SDK.fetchJSON(fileUrl, { method: "DELETE" }).then(() => navigatePath(pathForInbox(props.slug))).catch((err) => {
          setError(messageOf(err));
          setDeleting(false);
        });
      };
      if (loading) return h(LoadingState, { label: "Loading Inbox File\u2026" });
      if (error && !detail && !readOnly) {
        if (isNotFound(error)) {
          return h(
            "main",
            { className: "hermes-wiki" },
            h(BackLink, { href: pathForInbox(props.slug), label: "\u2190 Back to Inbox" }),
            h(ErrorState, { title: "Inbox file not found", message: "This inbox file was not found or is not visible." })
          );
        }
        return h(ErrorState, { title: "Failed to load Inbox File", message: error, onRetry: load });
      }
      const dirty = detail ? content !== detail.content : false;
      return h(
        "main",
        { className: "hermes-wiki" },
        h(BackLink, { href: pathForInbox(props.slug), label: "\u2190 Back to Inbox" }),
        h(
          "header",
          { className: "hermes-wiki-detail-hero" },
          h(
            "div",
            null,
            h("p", { className: "hermes-wiki-eyebrow" }, "Inbox File"),
            h("h1", null, props.filename),
            h(
              "p",
              { className: "hermes-wiki-muted" },
              detail ? `${detail.path} \xB7 ${formatBytes(detail.size_bytes)}` : `raw/inbox/${props.filename}`
            )
          ),
          detail ? h("div", { className: "hermes-wiki-tags" }, h(Badge, null, detail.classifier || "unknown"), h(Badge, null, detail.status)) : null
        ),
        error ? h(ErrorState, { title: "Inbox file update failed", message: error, onRetry: load }) : null,
        notice ? h(Card, { className: "hermes-wiki-notice" }, h(CardContent, null, notice)) : null,
        h(
          "section",
          { className: "hermes-wiki-inbox-file-editor" },
          readOnly ? null : h("textarea", {
            value: content,
            disabled: saving || deleting,
            spellCheck: false,
            "aria-label": `Edit ${props.filename}`,
            onChange: (event) => setContent(event.target.value)
          }),
          h(
            "div",
            { className: "hermes-wiki-inbox-file-actions" },
            readOnly ? null : h(Button, { disabled: saving || deleting || !dirty, onClick: save }, saving ? "Saving\u2026" : "Save"),
            h(
              Button,
              { className: "hermes-wiki-inbox-file-delete", disabled: saving || deleting, onClick: remove },
              deleting ? "Deleting\u2026" : "Delete"
            )
          )
        )
      );
    }, formatBytes = function(value) {
      if (!Number.isFinite(value) || value <= 0) return "0 B";
      const units = ["B", "KB", "MB", "GB"];
      let amount = value;
      let unit = 0;
      while (amount >= 1024 && unit < units.length - 1) {
        amount /= 1024;
        unit += 1;
      }
      return `${amount.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
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
    }, parseRoute = function(locationPath) {
      const url = new URL(locationPath, window.location.origin);
      const parts = url.pathname.replace(/^\/wikis\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
      if (!parts.length || parts[0] === "*") return { kind: "landing" };
      if (parts[0] === "search") {
        return {
          kind: "search",
          query: url.searchParams.get("q") || "",
          scope: url.searchParams.get("wiki") || ""
        };
      }
      const [slug, ...pageParts] = parts;
      if (!pageParts.length) return { kind: "wiki", slug };
      if (pageParts.length === 1 && pageParts[0] === "inbox") return { kind: "inbox", slug };
      if (pageParts.length === 2 && pageParts[0] === "inbox") {
        return { kind: "inboxFile", slug, filename: pageParts[1] };
      }
      if (pageParts.length === 1 && pageParts[0] === "health") return { kind: "health", slug };
      if (pageParts.length === 1 && pageParts[0] === "log") return { kind: "activity", slug };
      return { kind: "page", slug, pageId: pageParts.join("/") };
    }, WikiDashboard = function() {
      const [path, setPath] = useState(window.location.pathname + window.location.search);
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
      if (route.kind === "inboxFile") {
        return h(InboxFileRoute, { key: `inbox-file-${route.slug}-${route.filename}`, slug: route.slug, filename: route.filename });
      }
      if (route.kind === "health") return h(HealthRoute, { key: `health-${route.slug}`, slug: route.slug });
      if (route.kind === "activity") return h(ActivityRoute, { key: `activity-${route.slug}`, slug: route.slug });
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
