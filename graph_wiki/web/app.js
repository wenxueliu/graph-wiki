(() => {
  "use strict";

  const CATEGORY_PALETTE = [
    "#4E79A7", "#76B7B2", "#59A14F", "#F28E2B", "#E15759", "#B07AA1",
    "#EDC948", "#FF9DA7", "#9C755F", "#BAB0AC", "#8CD17D", "#A0CBE8",
  ];
  const RELATION_COLORS = {
    extends: "#59A14F",
    implements: "#4E79A7",
    contradicts: "#E15759",
    derived_from: "#F28E2B",
    uses: "#76B7B2",
    replaces: "#B07AA1",
    related_to: "#BAB0AC",
    supersedes: "#D37295",
    part_of: "#8CD17D",
    causes: "#F1CE63",
  };
  const UNTYPED_EDGE = "rgba(150, 156, 184, 0.38)";
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const state = {
    graph: null,
    network: null,
    nodeDataSet: null,
    edgeDataSet: null,
    nodeIndex: new Map(),
    categoryColors: new Map(),
    relationColors: new Map(),
    selected: null,
    pageRequest: 0,
    filterFrame: 0,
    loadingGraph: false,
  };

  const el = {};
  let toastTimer = 0;

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    cacheElements();
    bindEvents();
    if (typeof vis === "undefined") {
      showFatal(
        "The graph library failed to load. Restart the viewer from the installed package."
      );
      return;
    }
    loadGraph();
  }

  function cacheElements() {
    el.graph = document.getElementById("graph");
    el.graphWrap = document.getElementById("graph-wrap");
    el.loading = document.getElementById("loading");
    el.empty = document.getElementById("empty");
    el.error = document.getElementById("error");
    el.stats = document.getElementById("stats");
    el.search = document.getElementById("search");
    el.category = document.getElementById("category-filter");
    el.tag = document.getElementById("tag-filter");
    el.typedOnly = document.getElementById("typed-only");
    el.edgeLabels = document.getElementById("edge-labels");
    el.fit = document.getElementById("fit");
    el.refresh = document.getElementById("refresh");
    el.detail = document.getElementById("detail");
    el.legend = document.getElementById("legend");
    el.toast = document.getElementById("toast");
  }

  function bindEvents() {
    el.search.addEventListener("input", scheduleFilters);
    el.category.addEventListener("change", scheduleFilters);
    el.tag.addEventListener("change", scheduleFilters);
    el.typedOnly.addEventListener("change", scheduleFilters);
    el.edgeLabels.addEventListener("change", scheduleFilters);
    el.fit.addEventListener("click", fitGraph);
    el.refresh.addEventListener("click", () => loadGraph({ announce: true }));

    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", () => {
      if (state.network) state.network.redraw();
    });
  }

  async function loadGraph(options = {}) {
    if (state.loadingGraph) return;
    state.loadingGraph = true;
    el.refresh.disabled = true;
    hideError();
    if (!state.network) showLoading(true);

    try {
      const response = await fetch("/api/graph", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      const previousFingerprint = state.graph && state.graph.vault
        ? state.graph.vault.fingerprint
        : "";
      if (
        options.announce &&
        state.network &&
        previousFingerprint &&
        previousFingerprint === data.vault.fingerprint
      ) {
        toast("Already up to date");
        return;
      }
      state.graph = data;
      renderGraph(data);
      if (options.announce) toast("Graph refreshed");
    } catch (error) {
      showLoading(false);
      showError(`Could not load the graph: ${error.message || error}`);
    } finally {
      state.loadingGraph = false;
      el.refresh.disabled = false;
    }
  }

  function renderGraph(data) {
    if (state.network) {
      state.network.destroy();
      state.network = null;
    }
    state.nodeDataSet = null;
    state.edgeDataSet = null;
    el.graph.replaceChildren();
    el.empty.hidden = true;
    hideError();

    buildColors(data);
    state.nodeIndex = new Map(data.nodes.map((node) => [node.id, node]));
    fillSelect(el.category, "All categories", countEntries(data.stats.categories));
    fillSelect(el.tag, "All tags", countEntries(data.stats.tags));
    renderLegend(data);

    if (!data.nodes.length) {
      showLoading(false);
      el.empty.hidden = false;
      el.stats.textContent = "0 pages";
      el.legend.replaceChildren();
      renderEmptyDetail();
      return;
    }

    const nodes = data.nodes.map((node) => {
      const color = categoryColor(node.category);
      const degree = Number(node.degree) || 0;
      return {
        id: node.id,
        label: truncate(node.title, 44),
        title: nodeTooltip(node),
        size: Math.min(44, 9 + Math.sqrt(degree + 1) * 5.2),
        borderWidth: 1.2,
        color: {
          background: color,
          border: mixHex(color, "#0d0e17", 0.35),
          highlight: { background: color, border: "#ffffff" },
          hover: { background: color, border: "#ffffff" },
        },
        font: {
          size: 11,
          color: "#cfd2e6",
          face: "ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
          strokeWidth: 3,
          strokeColor: "#0d0e17",
        },
      };
    });

    const edges = data.edges.map((edge) => {
      const color = edge.typed ? relationColor(edge.relation) : UNTYPED_EDGE;
      return {
        id: edge.id,
        from: edge.source,
        to: edge.target,
        title: `${edge.source} → ${edge.target}\n${edge.relation}`,
        dashes: false,
        width: edge.typed ? Math.min(3, 1.1 + Number(edge.weight || 1) * 0.6) : 0.8,
        color: {
          color,
          highlight: color,
          hover: color,
          opacity: edge.typed ? 0.85 : 0.5,
        },
        arrows: edge.typed
          ? { to: { enabled: true, scaleFactor: 0.42 } }
          : { to: { enabled: false } },
        smooth: { enabled: true, type: "continuous", roundness: 0.18 },
        font: {
          size: el.edgeLabels.checked ? 9 : 0,
          color: "#aeb2c8",
          face: "ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
          strokeWidth: 3,
          strokeColor: "#0d0e17",
          align: "middle",
        },
      };
    });

    state.nodeDataSet = new vis.DataSet(nodes);
    state.edgeDataSet = new vis.DataSet(edges);

    const iterations = data.nodes.length > 1_200 ? 120 : 220;
    state.network = new vis.Network(
      el.graph,
      { nodes: state.nodeDataSet, edges: state.edgeDataSet },
      {
        autoResize: true,
        layout: { improvedLayout: true, randomSeed: 7 },
        physics: {
          solver: "forceAtlas2Based",
          forceAtlas2Based: {
            gravitationalConstant: -58,
            centralGravity: 0.006,
            springLength: 115,
            springConstant: 0.07,
            damping: 0.42,
            avoidOverlap: 0.15,
          },
          stabilization: {
            enabled: true,
            iterations,
            updateInterval: 25,
            fit: true,
          },
          maxVelocity: 40,
          minVelocity: 0.6,
        },
        interaction: {
          hover: true,
          tooltipDelay: 140,
          navigationButtons: false,
          keyboard: false,
          multiselect: false,
          selectConnectedEdges: true,
        },
        nodes: { shape: "dot", chosen: true },
        edges: {
          selectionWidth: 2,
          hoverWidth: 1.4,
          smooth: { enabled: true, type: "continuous", roundness: 0.18 },
        },
      }
    );

    state.network.on("click", (params) => {
      if (params.nodes && params.nodes.length) {
        selectNode(String(params.nodes[0]));
      } else {
        clearSelection();
      }
    });

    state.network.on("doubleClick", (params) => {
      if (params.nodes && params.nodes.length) {
        focusNode(String(params.nodes[0]));
      }
    });

    state.network.on("stabilizationProgress", (params) => {
      if (!el.loading.hidden && params.total) {
        const percent = Math.min(99, Math.round((params.iterations / params.total) * 100));
        el.loading.textContent = `Laying out the graph… ${percent}%`;
      }
    });

    const activeNetwork = state.network;
    activeNetwork.once("stabilizationIterationsDone", () => {
      if (state.network !== activeNetwork) return;
      activeNetwork.setOptions({ physics: { enabled: false } });
      finishLoading();
    });

    applyFilters();

    const previous = state.selected;
    const initial = new URLSearchParams(window.location.search).get("node");
    const target = previous && state.nodeIndex.has(previous) ? previous : initial;
    state.selected = null;
    if (target && state.nodeIndex.has(target)) {
      selectNode(target, { updateUrl: false });
    } else {
      renderEmptyDetail();
    }

    // A one-node graph can skip the stabilization callback on some browsers.
    window.setTimeout(() => {
      if (state.network === activeNetwork) finishLoading();
    }, 7_000);
  }

  function finishLoading() {
    const wasLoading = !el.loading.hidden;
    if (state.network) {
      state.network.setOptions({ physics: { enabled: false } });
      if (wasLoading) {
        state.network.fit({ animation: false, maxZoomLevel: 1.5 });
      }
    }
    showLoading(false);
    el.loading.textContent = "Laying out the graph…";
  }

  function buildColors(data) {
    const categories = Object.keys(data.stats.categories || {}).sort();
    state.categoryColors = new Map();
    categories.forEach((category, index) => {
      state.categoryColors.set(
        category,
        category === "(none)"
          ? "#4a4e6b"
          : CATEGORY_PALETTE[index % CATEGORY_PALETTE.length]
      );
    });

    const relations = [...new Set(
      data.edges.filter((edge) => edge.typed).map((edge) => edge.relation)
    )].sort();
    state.relationColors = new Map();
    relations.forEach((relation, index) => {
      state.relationColors.set(
        relation,
        RELATION_COLORS[relation] || CATEGORY_PALETTE[(index + 3) % CATEGORY_PALETTE.length]
      );
    });
  }

  function categoryColor(category) {
    return state.categoryColors.get(category) || "#4a4e6b";
  }

  function relationColor(relation) {
    return state.relationColors.get(relation) || "#8a8fb0";
  }

  function nodeTooltip(node) {
    const lines = [
      `<b>${escapeHtml(node.title)}</b>`,
      `${escapeHtml(node.category || "uncategorized")} · ${node.degree} connections`,
    ];
    if (node.tags && node.tags.length) {
      lines.push(escapeHtml(node.tags.map((tag) => `#${tag}`).join("  ")));
    }
    if (node.summary) {
      lines.push(escapeHtml(truncate(node.summary, 320)));
    }
    return lines.join("<br>");
  }

  function countEntries(counts) {
    return Object.entries(counts || {}).sort((a, b) => {
      if (b[1] !== a[1]) return b[1] - a[1];
      return a[0].localeCompare(b[0]);
    });
  }

  function fillSelect(select, allLabel, entries) {
    const current = select.value;
    select.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = allLabel;
    select.append(all);
    entries.forEach(([name, count]) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = `${name} (${count})`;
      select.append(option);
    });
    if ([...select.options].some((option) => option.value === current)) {
      select.value = current;
    }
  }

  function renderLegend(data) {
    el.legend.replaceChildren();
    const categories = countEntries(data.stats.categories);
    if (categories.length) {
      el.legend.append(heading("Categories"));
      const grid = document.createElement("div");
      grid.className = "legend-grid";
      categories.forEach(([category, count]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "legend-item";
        button.title = `Filter by ${category}`;
        button.append(dot(categoryColor(category)), span("name", category), span("count", String(count)));
        button.addEventListener("click", () => {
          el.category.value = category;
          scheduleFilters();
        });
        grid.append(button);
      });
      el.legend.append(grid);
    }

    const relationCounts = new Map();
    data.edges.forEach((edge) => {
      if (!edge.typed) return;
      relationCounts.set(edge.relation, (relationCounts.get(edge.relation) || 0) + 1);
    });
    if (relationCounts.size) {
      el.legend.append(heading("Relationships"));
      const grid = document.createElement("div");
      grid.className = "legend-grid";
      [...relationCounts.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .forEach(([relation, count]) => {
          const item = document.createElement("div");
          item.className = "legend-item static";
          item.append(dot(relationColor(relation)), span("name", relation), span("count", String(count)));
          grid.append(item);
        });
      el.legend.append(grid);
    }

    el.legend.append(heading("Links"));
    const untyped = document.createElement("div");
    untyped.className = "legend-item static";
    untyped.append(dot(UNTYPED_EDGE), span("name", "wikilink"), span("count", String(data.stats.untyped_edges || 0)));
    el.legend.append(untyped);
  }

  function scheduleFilters() {
    if (state.filterFrame) return;
    state.filterFrame = window.requestAnimationFrame(() => {
      state.filterFrame = 0;
      applyFilters();
    });
  }

  function applyFilters() {
    if (!state.graph || !state.nodeDataSet || !state.edgeDataSet) return;
    const query = (el.search.value || "").trim().toLowerCase();
    const category = el.category.value;
    const tag = el.tag.value;
    const typedOnly = el.typedOnly.checked;
    const showLabels = el.edgeLabels.checked;

    const visible = new Set();
    state.graph.nodes.forEach((node) => {
      if (category && node.category !== category) return;
      if (tag && !(node.tags || []).includes(tag)) return;
      if (query && !searchText(node).includes(query)) return;
      visible.add(node.id);
    });

    state.nodeDataSet.update(
      state.graph.nodes.map((node) => ({
        id: node.id,
        hidden: !visible.has(node.id),
      }))
    );

    let visibleEdges = 0;
    state.edgeDataSet.update(
      state.graph.edges.map((edge) => {
        const hiddenByNode = !visible.has(edge.source) || !visible.has(edge.target);
        const hiddenByType = typedOnly && !edge.typed;
        const hidden = hiddenByNode || hiddenByType;
        if (!hidden) visibleEdges += 1;
        return {
          id: edge.id,
          hidden,
          label: showLabels && edge.typed ? edge.relation : "",
          font: {
            size: showLabels && edge.typed ? 9 : 0,
            color: "#aeb2c8",
            face: "ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
            strokeWidth: 3,
            strokeColor: "#0d0e17",
            align: "middle",
          },
        };
      })
    );

    updateStats(visible.size, visibleEdges);
  }

  function updateStats(visiblePages, visibleEdges) {
    if (!state.graph) return;
    const stats = state.graph.stats;
    if (
      visiblePages === stats.pages &&
      visibleEdges === stats.edges
    ) {
      el.stats.textContent = `${stats.pages.toLocaleString()} pages · ${stats.edges.toLocaleString()} links · ${stats.typed_edges.toLocaleString()} typed`;
    } else {
      el.stats.textContent = `Showing ${visiblePages.toLocaleString()} / ${stats.pages.toLocaleString()} pages · ${visibleEdges.toLocaleString()} / ${stats.edges.toLocaleString()} links`;
    }
  }

  function searchText(node) {
    return [
      node.title,
      node.slug,
      node.category,
      node.path,
      (node.tags || []).join(" "),
      node.summary,
    ].join(" ").toLowerCase();
  }

  function selectNode(id, options = {}) {
    if (!state.graph) return;
    const node = state.nodeIndex.get(id);
    if (!node) return;

    state.selected = id;
    state.pageRequest += 1;
    const token = state.pageRequest;

    if (state.network) {
      state.network.selectNodes([id]);
    }
    if (options.updateUrl !== false) {
      setUrlNode(id);
    }
    renderDetail(node, null, { loading: true });

    fetch(`/api/page?id=${encodeURIComponent(id)}`, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((page) => {
        if (token !== state.pageRequest || state.selected !== id) return;
        renderDetail(node, page, { loading: false });
      })
      .catch((error) => {
        if (token !== state.pageRequest || state.selected !== id) return;
        renderDetail(node, null, { loading: false, error: error.message || String(error) });
      });
  }

  function clearSelection() {
    state.selected = null;
    state.pageRequest += 1;
    if (state.network) state.network.unselectAll();
    renderEmptyDetail();
    const url = new URL(window.location.href);
    url.searchParams.delete("node");
    window.history.replaceState({}, "", url);
  }

  function setUrlNode(id) {
    const url = new URL(window.location.href);
    url.searchParams.set("node", id);
    window.history.replaceState({}, "", url);
  }

  function focusNode(id) {
    if (!state.network || !state.nodeIndex.has(id)) return;
    state.network.focus(id, {
      scale: Math.max(1.15, state.network.getScale()),
      animation: REDUCED_MOTION ? false : { duration: 450, easingFunction: "easeInOutQuad" },
    });
  }

  function fitGraph() {
    if (!state.network) return;
    state.network.fit({
      maxZoomLevel: 1.5,
      animation: REDUCED_MOTION ? false : { duration: 400, easingFunction: "easeInOutQuad" },
    });
  }

  function renderEmptyDetail() {
    const wrapper = div("detail-empty");
    const title = document.createElement("h2");
    title.textContent = "Select a page";
    const text = document.createElement("p");
    text.textContent =
      "Click a node to see its summary, tags, and connections. Use the search and filters above to narrow the graph.";
    wrapper.append(title, text);
    el.detail.replaceChildren(wrapper);
  }

  function renderDetail(node, page, options = {}) {
    const fragment = document.createDocumentFragment();

    const head = div("detail-head");
    const headingWrap = document.createElement("div");
    const title = document.createElement("h2");
    title.className = "detail-title";
    title.textContent = node.title;
    headingWrap.append(title);

    const sub = div("detail-sub");
    sub.append(badge(node.category || "uncategorized", "accent"));
    sub.append(badge(`${node.degree} connections`));
    if (node.tier) sub.append(badge(node.tier));
    headingWrap.append(sub);
    head.append(headingWrap);
    fragment.append(head);

    if (node.tags && node.tags.length) {
      const tags = div("tags");
      node.tags.forEach((tag) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "tag";
        button.textContent = `#${tag}`;
        button.title = `Filter by #${tag}`;
        button.addEventListener("click", () => {
          if ([...el.tag.options].some((option) => option.value === tag)) {
            el.tag.value = tag;
            scheduleFilters();
          }
        });
        tags.append(button);
      });
      fragment.append(tags);
    }

    if (node.summary) {
      const summary = document.createElement("p");
      summary.className = "summary";
      summary.textContent = node.summary;
      fragment.append(summary);
    }

    const actions = div("actions");
    actions.append(
      actionButton("Open in Obsidian", () => openInObsidian(node, page)),
      actionButton("Focus", () => focusNode(node.id), true),
      actionButton("Copy link", () => copyText(window.location.href), true),
      actionButton(
        "Copy API",
        () => copyText(`${window.location.origin}/api/page?id=${encodeURIComponent(node.id)}`),
        true
      )
    );
    fragment.append(actions);

    const outgoing = state.graph.edges.filter((edge) => edge.source === node.id);
    const incoming = state.graph.edges.filter((edge) => edge.target === node.id);
    fragment.append(renderEdgeSection("Outgoing", outgoing, "target", "→"));
    fragment.append(renderEdgeSection("Incoming", incoming, "source", "←"));

    const pageBlock = div("page-block");
    pageBlock.append(heading("Page"));
    if (options.loading) {
      const loading = div("skeleton", "Loading page…");
      pageBlock.append(loading);
    } else if (options.error) {
      const error = div("page-note", `Could not load page body: ${options.error}`);
      pageBlock.append(error);
    } else if (page) {
      if (page.truncated) {
        pageBlock.append(
          div(
            "page-note",
            `Preview limited to ${Number(page.limit).toLocaleString()} of ${Number(page.bytes).toLocaleString()} bytes. Open in Obsidian for the full page.`
          )
        );
      }
      const body = document.createElement("pre");
      body.className = "page-body";
      body.textContent = page.body || "";
      pageBlock.append(body);
      if (page.frontmatter) {
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = "Frontmatter";
        const front = document.createElement("pre");
        front.className = "frontmatter";
        front.textContent = page.frontmatter;
        details.append(summary, front);
        pageBlock.append(details);
      }
    }
    fragment.append(pageBlock);

    el.detail.replaceChildren(fragment);
  }

  function renderEdgeSection(title, edges, otherKey, arrow) {
    const section = div("section");
    section.append(heading(`${title} (${edges.length})`));
    if (!edges.length) {
      section.append(div("page-note", "None"));
      return section;
    }
    const list = div("edge-list");
    edges.forEach((edge) => {
      const other = state.nodeIndex.get(edge[otherKey]);
      if (!other) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "edge-item";
      button.title = `${edge.source} → ${edge.target}`;
      button.append(
        span("rel", edge.typed ? edge.relation : "link"),
        span("dir", arrow),
        span("name", other.title)
      );
      button.addEventListener("click", () => selectNode(other.id));
      list.append(button);
    });
    section.append(list);
    return section;
  }

  function openInObsidian(node, page) {
    const uri = page && page.obsidian_uri
      ? page.obsidian_uri
      : obsidianUriFor(node);
    window.location.href = uri;
  }

  function obsidianUriFor(node) {
    const vaultPath = state.graph && state.graph.vault && state.graph.vault.path
      ? state.graph.vault.path
      : "";
    const absolute = `${vaultPath.replace(/\/+$/, "")}/${node.path}`;
    return `obsidian://open?path=${encodeURIComponent(absolute)}`;
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied");
    } catch (error) {
      window.prompt("Copy", text);
    }
  }

  function showLoading(show) {
    el.loading.hidden = !show;
  }

  function showError(message) {
    el.error.replaceChildren();
    el.error.append(document.createTextNode(`${message} `));
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", () => loadGraph());
    el.error.append(retry);
    el.error.hidden = false;
  }

  function hideError() {
    el.error.hidden = true;
    el.error.replaceChildren();
  }

  function showFatal(message) {
    showLoading(false);
    el.stats.textContent = "Viewer unavailable";
    el.error.textContent = message;
    el.error.hidden = false;
  }

  function toast(message) {
    el.toast.textContent = message;
    el.toast.classList.add("visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
      el.toast.classList.remove("visible");
    }, 2_200);
  }

  function onKeyDown(event) {
    const target = event.target;
    const typing = target && (
      target.tagName === "INPUT" ||
      target.tagName === "SELECT" ||
      target.tagName === "TEXTAREA"
    );

    if (event.key === "/" && !typing) {
      event.preventDefault();
      el.search.focus();
      return;
    }
    if (event.key === "Escape") {
      if (document.activeElement === el.search && el.search.value) {
        el.search.value = "";
        scheduleFilters();
      } else {
        clearSelection();
      }
      return;
    }
    if (
      !typing &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey &&
      event.key.toLowerCase() === "f"
    ) {
      event.preventDefault();
      fitGraph();
    }
  }

  function heading(text) {
    const node = document.createElement("h3");
    node.textContent = text;
    return node;
  }

  function badge(text, variant) {
    const node = document.createElement("span");
    node.className = variant ? `badge ${variant}` : "badge";
    node.textContent = text;
    return node;
  }

  function dot(color) {
    const node = document.createElement("span");
    node.className = "dot";
    node.style.background = color;
    return node;
  }

  function span(className, text) {
    const node = document.createElement("span");
    node.className = className;
    node.textContent = text;
    return node;
  }

  function div(className, text) {
    const node = document.createElement("div");
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function actionButton(label, handler, ghost = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = ghost ? "button ghost" : "button";
    button.textContent = label;
    button.addEventListener("click", handler);
    return button;
  }

  function truncate(value, limit) {
    const text = String(value || "");
    return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => {
      switch (char) {
        case "&": return "&amp;";
        case "<": return "&lt;";
        case ">": return "&gt;";
        case '"': return "&quot;";
        case "'": return "&#39;";
        default: return char;
      }
    });
  }

  function mixHex(color, target, amount) {
    const parse = (value) => value.replace("#", "").match(/.{2}/g).map((part) => parseInt(part, 16));
    const a = parse(color);
    const b = parse(target);
    if (!a || !b || a.length !== 3 || b.length !== 3) return color;
    const mixed = a.map((channel, index) => Math.round(channel + (b[index] - channel) * amount));
    return `#${mixed.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
  }
})();
