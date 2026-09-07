/* Boardroom responsiveness + in-widget interaction, entirely client-side.
 *
 * Why this exists: the Boardroom is a governed 12-column grid whose spans are
 * INLINE styles (render.py writes `grid-column: span N`), so a media query
 * cannot soften them — only script can. And a widget filter that went through a
 * Dash callback would re-render the whole card to hide three rows. Both belong
 * in the browser.
 *
 * Three behaviours, all driven by data attributes the renderers emit:
 *
 *   [data-bm-grid]                a grid to watch; gets data-bm-size = xs|sm|md|lg
 *   select[data-bm-filter=NAME]   a filter; rows carry data-NAME
 *   [data-bm-filter-target=NAME]  the container whose rows that filter hides
 *   [data-bm-filter-empty=NAME]   the "nothing matches" hint for that filter
 *
 * Everything is event-delegated or (re)attached by a MutationObserver, so it
 * survives every Dash re-render. Nothing here is required for the page to work:
 * with the script blocked, the board renders at full width and shows all rows.
 */
(function () {
  "use strict";

  // Grid width -> layout bucket, and the NARROWEST span allowed in it. Widths
  // only ever widen: a half-width widget goes full-bleed on a phone, but a
  // full-width one is never cut to half on a laptop.
  const BREAKPOINTS = [
    { name: "xs", max: 560, minSpan: 12 },
    { name: "sm", max: 820, minSpan: 12 },
    { name: "md", max: 1180, minSpan: 6 },
    { name: "lg", max: Infinity, minSpan: 1 },
  ];

  function bucketFor(width) {
    return BREAKPOINTS.find(function (bp) {
      return width <= bp.max;
    }) || BREAKPOINTS[BREAKPOINTS.length - 1];
  }

  const TOTAL_COLUMNS = 12;

  function authoredSpan(widget) {
    // The span the document asked for. Read once from the inline style the
    // renderer wrote, then remembered — later passes read our own value back.
    if (!widget.dataset.bmSpan) {
      const match = /span\s+(\d+)/.exec(widget.style.gridColumn || "");
      widget.dataset.bmSpan = match ? match[1] : String(TOTAL_COLUMNS);
    }
    return Number(widget.dataset.bmSpan) || TOTAL_COLUMNS;
  }

  function applySpans(grid, minSpan) {
    Array.prototype.forEach.call(grid.children, function (widget) {
      if (!widget.style) return;
      const span = Math.min(TOTAL_COLUMNS, Math.max(authoredSpan(widget), minSpan));
      const next = "span " + span;
      if (widget.style.gridColumn !== next) widget.style.gridColumn = next;
    });
  }

  /* ── responsive grids ───────────────────────────────────────────────── */

  let resizeNudge = null;

  function nudgePlotly() {
    // Plotly graphs are configured `responsive: true`, which listens for a
    // window resize — a grid that reflows without one leaves charts at their
    // old width. Debounced so a drag-resize fires once, not sixty times.
    if (resizeNudge) window.clearTimeout(resizeNudge);
    resizeNudge = window.setTimeout(function () {
      window.dispatchEvent(new Event("resize"));
    }, 120);
  }

  function applyBucket(grid) {
    // A grid on a hidden page measures 0 — that is "not on screen", not "tiny".
    // The observer fires again with a real width when its page is shown.
    if (!grid.clientWidth) return;
    const bucket = bucketFor(grid.clientWidth);
    // Re-apply the spans even when the bucket is unchanged: a Dash re-render
    // replaces the widgets with freshly authored inline styles.
    applySpans(grid, bucket.minSpan);
    if (grid.dataset.bmSize === bucket.name) return;
    grid.dataset.bmSize = bucket.name;
    nudgePlotly();
  }

  const observer =
    typeof ResizeObserver === "function"
      ? new ResizeObserver(function (entries) {
          entries.forEach(function (entry) {
            applyBucket(entry.target);
          });
        })
      : null;

  function watchGrids(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("[data-bm-grid]").forEach(function (grid) {
      applyBucket(grid);
      if (observer && !grid.dataset.bmWatched) {
        grid.dataset.bmWatched = "1";
        observer.observe(grid);
      }
    });
  }

  /* ── widget filters (product line, and anything shaped like it) ──────── */

  function widgetOf(el) {
    return el.closest(".bm-widget, .bm-gw") || document;
  }

  function applyFilter(select) {
    const name = select.dataset.bmFilter;
    if (!name) return;
    const scope = widgetOf(select);
    const target = scope.querySelector('[data-bm-filter-target="' + name + '"]');
    if (!target) return;
    const want = (select.value || "all").toLowerCase();
    let shown = 0;
    Array.prototype.forEach.call(target.children, function (row) {
      const value = (row.dataset[name] || "").toLowerCase();
      const match = want === "all" || !value || value === want;
      row.hidden = !match;
      if (match) shown += 1;
    });
    const empty = scope.querySelector('[data-bm-filter-empty="' + name + '"]');
    if (empty) empty.hidden = shown > 0;
  }

  function applyAllFilters(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("select[data-bm-filter]").forEach(applyFilter);
  }

  document.addEventListener("change", function (e) {
    const select =
      e.target && e.target.closest ? e.target.closest("select[data-bm-filter]") : null;
    if (select) applyFilter(select);
  });

  /* ── keep working across Dash re-renders ─────────────────────────────── */

  function refresh(root) {
    watchGrids(root);
    applyAllFilters(root);
  }

  const dom = new MutationObserver(function (mutations) {
    let touched = false;
    mutations.forEach(function (m) {
      Array.prototype.forEach.call(m.addedNodes, function (node) {
        if (node.nodeType !== 1) return;
        if (
          node.matches("[data-bm-grid], select[data-bm-filter]") ||
          node.querySelector("[data-bm-grid], select[data-bm-filter]")
        ) {
          touched = true;
        }
      });
    });
    if (touched) refresh(document);
  });

  function start() {
    refresh(document);
    dom.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("resize", function () {
      watchGrids(document);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
