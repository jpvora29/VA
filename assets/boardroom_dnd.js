/* Boardroom drag-and-drop widget reordering (edit mode).
 *
 * Wiring: render.py gives each editable widget a `.bm-grip` handle and stamps
 * the card root (.bm-gw) with data-wid / data-card. Dragging a grip and
 * dropping on another widget in the SAME boardroom card writes
 * {card, src, dst, before} into the `bm-dnd` dcc.Store via
 * dash_clientside.set_props; the server callback `dnd_reorder` in
 * ui/boardroom/callbacks.py applies the move to the document.
 *
 * Event delegation on document keeps this working across Dash re-renders.
 */
(function () {
  "use strict";

  let dragSrc = null; // { wid, card }

  function widgetOf(el) {
    return el && el.closest ? el.closest(".bm-gw") : null;
  }

  function clearIndicators() {
    document
      .querySelectorAll(".bm-dragging, .bm-drop-before, .bm-drop-after")
      .forEach(function (el) {
        el.classList.remove("bm-dragging", "bm-drop-before", "bm-drop-after");
      });
  }

  document.addEventListener("dragstart", function (e) {
    const grip = e.target && e.target.closest ? e.target.closest(".bm-grip") : null;
    if (!grip) return;
    const card = widgetOf(grip);
    if (!card || !card.dataset.wid) return;
    dragSrc = { wid: card.dataset.wid, card: card.dataset.card };
    card.classList.add("bm-dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", card.dataset.wid);
    if (e.dataTransfer.setDragImage) {
      e.dataTransfer.setDragImage(card, 24, 24);
    }
  });

  document.addEventListener("dragover", function (e) {
    if (!dragSrc) return;
    const tgt = widgetOf(e.target);
    if (
      !tgt ||
      !tgt.dataset.wid ||
      tgt.dataset.card !== dragSrc.card ||
      tgt.dataset.wid === dragSrc.wid
    ) {
      return;
    }
    e.preventDefault(); // allow the drop
    e.dataTransfer.dropEffect = "move";
    const r = tgt.getBoundingClientRect();
    const before = e.clientX - r.left < r.width / 2;
    tgt.classList.toggle("bm-drop-before", before);
    tgt.classList.toggle("bm-drop-after", !before);
  });

  document.addEventListener("dragleave", function (e) {
    const tgt = widgetOf(e.target);
    if (tgt) tgt.classList.remove("bm-drop-before", "bm-drop-after");
  });

  document.addEventListener("drop", function (e) {
    if (!dragSrc) return;
    const tgt = widgetOf(e.target);
    if (
      !tgt ||
      !tgt.dataset.wid ||
      tgt.dataset.card !== dragSrc.card ||
      tgt.dataset.wid === dragSrc.wid
    ) {
      clearIndicators();
      dragSrc = null;
      return;
    }
    e.preventDefault();
    const r = tgt.getBoundingClientRect();
    const before = e.clientX - r.left < r.width / 2;
    if (window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props("bm-dnd", {
        data: {
          card: Number(dragSrc.card),
          src: dragSrc.wid,
          dst: tgt.dataset.wid,
          before: before,
          ts: Date.now(), // makes consecutive identical moves distinct
        },
      });
    }
    clearIndicators();
    dragSrc = null;
  });

  document.addEventListener("dragend", function () {
    clearIndicators();
    dragSrc = null;
  });
})();
