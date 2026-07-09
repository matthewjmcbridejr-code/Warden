/* Warden Brain Graph — neural map view over vault sources + agent memory. */
(function () {
  "use strict";

  const GRAPH_URL = "/api/brain/graph";
  const SEARCH_URL = "/api/mcharness/warden/brain/search";
  const W = 900;
  const H = 600;

  const TYPE_META = {
    project: { color: "#7db0ff", label: "Project" },
    person: { color: "#a78bfa", label: "Person" },
    client: { color: "#f472b6", label: "Client" },
    system: { color: "#f0c66a", label: "System" },
    research: { color: "#5eead4", label: "Research" },
    note: { color: "#8fa3be", label: "Note" },
    inbox: { color: "#5b6b82", label: "Inbox / raw" },
    proof: { color: "#63db9d", label: "Proof" },
    decision: { color: "#38bdf8", label: "Decision" },
    failure: { color: "#ff7e91", label: "Failure" },
    handoff: { color: "#fb923c", label: "Handoff" },
  };
  const TYPE_ORDER = ["project", "system", "person", "client", "research", "note", "inbox", "proof", "decision", "failure", "handoff"];

  let _nodes = [];
  let _edges = [];
  let _selectedId = null;
  let _activeTypes = new Set(TYPE_ORDER);
  let _statusFilter = "";
  let _projectFilter = "";
  let _searchTerm = "";
  let _loaded = false;

  /* -------------------------------------------------------------- */
  /* Pan / zoom / drag — Obsidian-style graph navigation.             */
  /* -------------------------------------------------------------- */
  let _viewBox = { x: 0, y: 0, w: W, h: H };

  function clientToSvg(svg, clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    return {
      x: _viewBox.x + ((clientX - rect.left) / rect.width) * _viewBox.w,
      y: _viewBox.y + ((clientY - rect.top) / rect.height) * _viewBox.h,
    };
  }

  function applyViewBox(svg) {
    svg.setAttribute("viewBox", `${_viewBox.x} ${_viewBox.y} ${_viewBox.w} ${_viewBox.h}`);
  }

  function edgePathD(a, b) {
    const mx = (a.x + b.x) / 2 + (a.y - b.y) * 0.08;
    const my = (a.y + b.y) / 2 + (b.x - a.x) * 0.08;
    return `M${a.x},${a.y} Q${mx},${my} ${b.x},${b.y}`;
  }

  function updateNodePosition(svg, node) {
    const g = svg.querySelector(`.bg-node[data-node-id="${CSS.escape(node.id)}"]`);
    if (g) g.setAttribute("transform", `translate(${node.x},${node.y})`);
    const byId = new Map(_nodes.map((n) => [n.id, n]));
    svg.querySelectorAll(
      `path.bg-edge[data-source="${CSS.escape(node.id)}"], path.bg-edge[data-target="${CSS.escape(node.id)}"]`
    ).forEach((p) => {
      const s = byId.get(p.dataset.source), t = byId.get(p.dataset.target);
      if (s && t) p.setAttribute("d", edgePathD(s, t));
    });
  }

  function onWheelZoom(ev) {
    ev.preventDefault();
    const svg = ev.currentTarget;
    const before = clientToSvg(svg, ev.clientX, ev.clientY);
    const factor = ev.deltaY > 0 ? 1.12 : 1 / 1.12;
    let newW = Math.max(120, Math.min(W * 5, _viewBox.w * factor));
    let newH = Math.max(80, Math.min(H * 5, _viewBox.h * factor));
    _viewBox.x = before.x - ((before.x - _viewBox.x) * (newW / _viewBox.w));
    _viewBox.y = before.y - ((before.y - _viewBox.y) * (newH / _viewBox.h));
    _viewBox.w = newW;
    _viewBox.h = newH;
    applyViewBox(svg);
  }

  function bindCanvasPanZoom(svg) {
    if (svg.dataset.bgNavBound) return;
    svg.dataset.bgNavBound = "1";
    svg.classList.add("bg-svg-interactive");
    svg.addEventListener("wheel", onWheelZoom, { passive: false });
    svg.addEventListener("pointerdown", (ev) => {
      if (ev.target.closest && ev.target.closest(".bg-node")) return;
      svg.setPointerCapture(ev.pointerId);
      svg.classList.add("bg-panning");
      const start = { x: ev.clientX, y: ev.clientY };
      const startVB = { x: _viewBox.x, y: _viewBox.y };
      const onMove = (mv) => {
        const rect = svg.getBoundingClientRect();
        const dx = ((mv.clientX - start.x) / rect.width) * _viewBox.w;
        const dy = ((mv.clientY - start.y) / rect.height) * _viewBox.h;
        _viewBox.x = startVB.x - dx;
        _viewBox.y = startVB.y - dy;
        applyViewBox(svg);
      };
      const onUp = (uv) => {
        svg.releasePointerCapture(uv.pointerId);
        svg.classList.remove("bg-panning");
        svg.removeEventListener("pointermove", onMove);
        svg.removeEventListener("pointerup", onUp);
      };
      svg.addEventListener("pointermove", onMove);
      svg.addEventListener("pointerup", onUp);
    });
    svg.addEventListener("dblclick", (ev) => {
      if (ev.target.closest && ev.target.closest(".bg-node")) return;
      _viewBox = { x: 0, y: 0, w: W, h: H };
      applyViewBox(svg);
    });
  }

  function bindNodeDrag(svg, el, node) {
    el.addEventListener("pointerdown", (ev) => {
      ev.stopPropagation();
      el.setPointerCapture(ev.pointerId);
      hideTooltip();
      const startClient = { x: ev.clientX, y: ev.clientY };
      const startSvg = clientToSvg(svg, ev.clientX, ev.clientY);
      const offX = node.x - startSvg.x, offY = node.y - startSvg.y;
      let moved = false;
      const onMove = (mv) => {
        if (Math.abs(mv.clientX - startClient.x) > 2 || Math.abs(mv.clientY - startClient.y) > 2) moved = true;
        const p = clientToSvg(svg, mv.clientX, mv.clientY);
        node.x = p.x + offX;
        node.y = p.y + offY;
        updateNodePosition(svg, node);
      };
      const onUp = (uv) => {
        el.releasePointerCapture(uv.pointerId);
        el.removeEventListener("pointermove", onMove);
        el.removeEventListener("pointerup", onUp);
        if (!moved) selectNode(node.id);
      };
      el.addEventListener("pointermove", onMove);
      el.addEventListener("pointerup", onUp);
    });
  }

  /* -------------------------------------------------------------- */
  /* Force-directed layout — simple, synchronous, good enough for a  */
  /* personal vault (tens to low hundreds of nodes).                 */
  /* -------------------------------------------------------------- */
  function layout(nodes, edges) {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * Math.PI * 2;
      const r = 120 + (i % 5) * 40;
      n.x = W / 2 + Math.cos(angle) * r;
      n.y = H / 2 + Math.sin(angle) * r;
      n.vx = 0;
      n.vy = 0;
    });
    const iterations = nodes.length > 150 ? 60 : 140;
    for (let iter = 0; iter < iterations; iter++) {
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          let dx = a.x - b.x, dy = a.y - b.y;
          let dist2 = dx * dx + dy * dy;
          if (dist2 < 1) dist2 = 1;
          const force = 2600 / dist2;
          const dist = Math.sqrt(dist2);
          const fx = (dx / dist) * force, fy = (dy / dist) * force;
          a.vx += fx; a.vy += fy;
          b.vx -= fx; b.vy -= fy;
        }
      }
      edges.forEach((e) => {
        const a = byId.get(e.source), b = byId.get(e.target);
        if (!a || !b) return;
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const target = 90 + (4 - Math.min(e.weight || 1, 3)) * 20;
        const pull = (dist - target) * 0.02;
        const fx = (dx / dist) * pull, fy = (dy / dist) * pull;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      });
      nodes.forEach((n) => {
        const cx = W / 2, cy = H / 2;
        n.vx += (cx - n.x) * 0.002;
        n.vy += (cy - n.y) * 0.002;
        n.vx *= 0.82; n.vy *= 0.82;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(30, Math.min(W - 30, n.x));
        n.y = Math.max(30, Math.min(H - 30, n.y));
      });
    }
  }

  /* -------------------------------------------------------------- */
  /* Filtering                                                       */
  /* -------------------------------------------------------------- */
  function nodeVisible(n) {
    if (!_activeTypes.has(n.type)) return false;
    if (_statusFilter && n.status !== _statusFilter) return false;
    if (_projectFilter && n.project !== _projectFilter) return false;
    return true;
  }

  function nodeMatchesSearch(n) {
    if (!_searchTerm) return false;
    const hay = `${n.label} ${(n.tags || []).join(" ")} ${n.project || ""}`.toLowerCase();
    return hay.includes(_searchTerm);
  }

  function relTime(iso) {
    if (!iso) return "";
    const diff = Date.now() - new Date(iso).getTime();
    if (Number.isNaN(diff)) return "";
    const m = Math.floor(diff / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  /* -------------------------------------------------------------- */
  /* Rendering                                                        */
  /* -------------------------------------------------------------- */
  function render() {
    const svg = document.getElementById("bg-svg");
    const empty = document.getElementById("bg-empty");
    if (!svg) return;

    if (!_nodes.length) {
      svg.innerHTML = "";
      if (empty) empty.style.display = "";
      return;
    }
    if (empty) empty.style.display = "none";

    const byId = new Map(_nodes.map((n) => [n.id, n]));
    const visibleIds = new Set(_nodes.filter(nodeVisible).map((n) => n.id));

    let svgContent = `<defs>
      <filter id="bg-glow" x="-60%" y="-60%" width="220%" height="220%">
        <feGaussianBlur stdDeviation="3.2" result="blur" />
        <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
    </defs>`;

    svgContent += `<g id="bg-edges">`;
    _edges.forEach((e) => {
      const a = byId.get(e.source), b = byId.get(e.target);
      if (!a || !b) return;
      if (!visibleIds.has(a.id) || !visibleIds.has(b.id)) return;
      const active = _selectedId && (a.id === _selectedId || b.id === _selectedId);
      const opacity = active ? 0.85 : e.type === "link" ? 0.45 : e.type === "project" ? 0.3 : 0.16;
      svgContent += `<path class="bg-edge${active ? " bg-edge-active" : ""}" data-source="${escapeHtml(e.source)}" data-target="${escapeHtml(e.target)}" d="${edgePathD(a, b)}" fill="none" stroke="var(--line-glow)" stroke-width="${active ? Math.min((e.weight || 1) + 1, 4) : Math.min(e.weight || 1, 3)}" opacity="${opacity}" />`;
    });
    svgContent += `</g><g id="bg-nodes">`;

    _nodes.forEach((n) => {
      const visible = visibleIds.has(n.id);
      const meta = TYPE_META[n.type] || TYPE_META.note;
      const matched = nodeMatchesSearch(n);
      const dimmed = !visible || (_searchTerm && !matched);
      const selected = n.id === _selectedId;
      const r = Math.max(5, (n.size || 10) / 2);
      svgContent += `<g class="bg-node${dimmed ? " bg-node-dim" : ""}${selected ? " bg-node-selected" : ""}" data-node-id="${n.id}" transform="translate(${n.x},${n.y})">
        ${selected ? `<circle r="${r + 6}" fill="none" stroke="${meta.color}" stroke-width="1.5" opacity="0.9" />` : ""}
        <circle r="${r}" fill="${meta.color}" opacity="${dimmed ? 0.28 : matched ? 1 : 0.88}" filter="${dimmed ? "" : "url(#bg-glow)"}" />
        ${r > 9 || selected ? `<text class="bg-node-label" x="0" y="${r + 13}" text-anchor="middle">${escapeHtml(n.label.slice(0, 22))}</text>` : ""}
      </g>`;
    });
    svgContent += `</g>`;
    svg.innerHTML = svgContent;
    applyViewBox(svg);

    svg.querySelectorAll(".bg-node").forEach((el) => {
      const id = el.dataset.nodeId;
      const node = byId.get(id);
      el.addEventListener("mouseenter", (ev) => showTooltip(node, ev));
      el.addEventListener("mousemove", (ev) => moveTooltip(ev));
      el.addEventListener("mouseleave", hideTooltip);
      bindNodeDrag(svg, el, node);
    });
    bindCanvasPanZoom(svg);
  }

  /* -------------------------------------------------------------- */
  /* Tooltip (hover preview)                                          */
  /* -------------------------------------------------------------- */
  function showTooltip(n, ev) {
    if (!n) return;
    const tip = document.getElementById("bg-tooltip");
    if (!tip) return;
    const meta = TYPE_META[n.type] || TYPE_META.note;
    tip.innerHTML = `<div class="bg-tooltip-title">${escapeHtml(n.label)}</div>
      <div class="bg-tooltip-meta"><span class="bg-type-dot" style="background:${meta.color}"></span>${meta.label}${n.project ? ` · ${escapeHtml(n.project)}` : ""}</div>
      ${n.updated_at ? `<div class="bg-tooltip-time">${relTime(n.updated_at)}</div>` : ""}`;
    tip.style.display = "block";
    moveTooltip(ev);
  }

  function moveTooltip(ev) {
    const tip = document.getElementById("bg-tooltip");
    const wrap = document.getElementById("bg-canvas-wrap");
    if (!tip || !wrap) return;
    const rect = wrap.getBoundingClientRect();
    tip.style.left = `${ev.clientX - rect.left + 14}px`;
    tip.style.top = `${ev.clientY - rect.top + 10}px`;
  }

  function hideTooltip() {
    const tip = document.getElementById("bg-tooltip");
    if (tip) tip.style.display = "none";
  }

  /* -------------------------------------------------------------- */
  /* Detail panel                                                     */
  /* -------------------------------------------------------------- */
  function selectNode(id) {
    _selectedId = id;
    render();
    const n = _nodes.find((x) => x.id === id);
    const panel = document.getElementById("bg-detail-panel");
    if (!panel || !n) return;
    const meta = TYPE_META[n.type] || TYPE_META.note;
    panel.innerHTML = `
      <div class="bg-detail-type"><span class="bg-type-dot" style="background:${meta.color}"></span>${meta.label}</div>
      <h3 class="bg-detail-title">${escapeHtml(n.label)}</h3>
      <div class="bg-detail-row"><span class="bg-detail-label">Status</span><span>${escapeHtml(n.status || "—")}</span></div>
      ${n.project ? `<div class="bg-detail-row"><span class="bg-detail-label">Project</span><span>${escapeHtml(n.project)}</span></div>` : ""}
      ${n.updated_at ? `<div class="bg-detail-row"><span class="bg-detail-label">Updated</span><span>${relTime(n.updated_at)}</span></div>` : ""}
      ${n.path ? `<div class="bg-detail-row"><span class="bg-detail-label">Source</span><span class="mono bg-detail-path">${escapeHtml(n.path)}</span></div>` : ""}
      ${(n.tags || []).length ? `<div class="bg-detail-tags">${n.tags.map((t) => `<span class="memory-chip">${escapeHtml(t)}</span>`).join("")}</div>` : ""}
      <button type="button" class="btn" id="bg-search-related-btn">Search Brain for this</button>
      <div id="bg-detail-search-results" class="bg-detail-search-results"></div>
    `;
    document.getElementById("bg-search-related-btn")?.addEventListener("click", () => searchRelated(n.label));
  }

  async function searchRelated(query) {
    const el = document.getElementById("bg-detail-search-results");
    if (!el) return;
    el.innerHTML = `<span class="muted" style="font-size:0.78rem;">Searching…</span>`;
    try {
      const res = await fetch(`${SEARCH_URL}?q=${encodeURIComponent(query)}&limit=5`);
      const data = await res.json();
      const items = data.results || [];
      if (!items.length) {
        el.innerHTML = `<span class="muted" style="font-size:0.78rem;">No matches.</span>`;
        return;
      }
      el.innerHTML = items
        .map((r) => `<div class="brain-result-item"><div class="brain-result-title">${escapeHtml(r.title || r.path || "Result")}</div><div class="brain-result-summary">${escapeHtml((r.excerpt || r.text || "").slice(0, 140))}</div></div>`)
        .join("");
    } catch {
      el.innerHTML = `<span class="muted" style="font-size:0.78rem;">Search failed.</span>`;
    }
  }

  /* -------------------------------------------------------------- */
  /* Filter UI                                                        */
  /* -------------------------------------------------------------- */
  function buildTypeFilters() {
    const host = document.getElementById("bg-type-filters");
    if (!host) return;
    const present = new Set(_nodes.map((n) => n.type));
    host.innerHTML = TYPE_ORDER.filter((t) => present.has(t))
      .map((t) => {
        const meta = TYPE_META[t];
        return `<button type="button" class="bg-type-chip active" data-type="${t}">
          <span class="bg-type-dot" style="background:${meta.color}"></span>${meta.label}
        </button>`;
      })
      .join("");
    host.querySelectorAll(".bg-type-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const t = chip.dataset.type;
        if (_activeTypes.has(t)) { _activeTypes.delete(t); chip.classList.remove("active"); }
        else { _activeTypes.add(t); chip.classList.add("active"); }
        render();
      });
    });
  }

  function buildProjectFilter() {
    const sel = document.getElementById("bg-project-filter");
    if (!sel) return;
    const projects = Array.from(new Set(_nodes.map((n) => n.project).filter(Boolean))).sort();
    sel.innerHTML = `<option value="">All projects</option>` + projects.map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("");
  }

  function buildLegend() {
    const host = document.getElementById("bg-legend");
    if (!host) return;
    const present = new Set(_nodes.map((n) => n.type));
    host.innerHTML = TYPE_ORDER.filter((t) => present.has(t))
      .map((t) => `<span class="bg-legend-item"><span class="bg-type-dot" style="background:${TYPE_META[t].color}"></span>${TYPE_META[t].label}</span>`)
      .join("");
  }

  /* -------------------------------------------------------------- */
  /* Data loading                                                     */
  /* -------------------------------------------------------------- */
  async function load(force) {
    if (_loaded && !force) { render(); return; }
    const wrap = document.getElementById("bg-canvas-wrap");
    const empty = document.getElementById("bg-empty");
    if (empty) empty.style.display = "none";
    if (wrap) wrap.classList.add("bg-loading");
    try {
      const res = await fetch(GRAPH_URL);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      _nodes = data.nodes || [];
      _edges = data.edges || [];
      _activeTypes = new Set(TYPE_ORDER);
      _viewBox = { x: 0, y: 0, w: W, h: H };
      layout(_nodes, _edges);
      buildTypeFilters();
      buildProjectFilter();
      buildLegend();
      render();
      _loaded = true;
    } catch (e) {
      const empty2 = document.getElementById("bg-empty");
      if (empty2) {
        empty2.style.display = "";
        empty2.innerHTML = `<p>Could not load the brain graph.</p><p class="muted">${escapeHtml(e.message || "")}</p>`;
      }
    } finally {
      if (wrap) wrap.classList.remove("bg-loading");
    }
  }

  function bindEvents() {
    document.getElementById("bg-refresh")?.addEventListener("click", () => load(true));
    document.getElementById("bg-search-input")?.addEventListener("input", (e) => {
      _searchTerm = (e.target.value || "").trim().toLowerCase();
      render();
    });
    document.getElementById("bg-status-filter")?.addEventListener("change", (e) => {
      _statusFilter = e.target.value;
      render();
    });
    document.getElementById("bg-project-filter")?.addEventListener("change", (e) => {
      _projectFilter = e.target.value;
      render();
    });
  }

  /* -------------------------------------------------------------- */
  /* Init                                                             */
  /* -------------------------------------------------------------- */
  function init() {
    bindEvents();
    if (document.querySelector('.workspace-section[data-section="brain-graph"].active')) {
      load();
    }
  }

  window.WardenBrainGraph = { load };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
