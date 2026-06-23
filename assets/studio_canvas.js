/* Boardroom Canvas direct manipulation — move, resize, select.
   The canvas surface owns all pointer interaction; on drop it writes the result
   to the hidden #qs-cv-sink input, which a Dash callback commits to the shared
   document. Event delegation on `document` so it survives Dash re-renders. */
(function () {
  "use strict";

  var drag = null;

  function surface() { return document.getElementById("qs-cv-surface"); }

  function commit(payload) {
    var sink = document.getElementById("qs-cv-sink");
    if (!sink) return;
    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    // append a nonce so two identical actions still register as a value change
    setter.call(sink, JSON.stringify(payload) + "@" + Date.now());
    sink.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function geom(el) {
    return {
      x: parseFloat(el.getAttribute("data-x")),
      y: parseFloat(el.getAttribute("data-y")),
      w: parseFloat(el.getAttribute("data-w")),
      h: parseFloat(el.getAttribute("data-h")),
    };
  }

  document.addEventListener("pointerdown", function (e) {
    var s = surface();
    if (!s) return;
    var widget = e.target.closest(".qs-cv-widget");
    if (!widget || !s.contains(widget)) return;

    var rect = s.getBoundingClientRect();
    var cols = parseInt(s.getAttribute("data-cols"), 10) || 12;
    var rows = parseInt(s.getAttribute("data-rows"), 10) || 8;
    var scaleX = rect.width / (s.offsetWidth || rect.width);
    var scaleY = rect.height / (s.offsetHeight || rect.height);
    var cellW = (s.offsetWidth || rect.width) / cols;
    var cellH = (s.offsetHeight || rect.height) / rows;
    var handle = e.target.closest(".qs-cv-handle");
    var g = geom(widget);

    drag = {
      el: widget,
      wid: widget.getAttribute("data-wid"),
      mode: handle ? "resize" : "move",
      handle: handle ? handle.getAttribute("data-h") : null,
      sx: e.clientX, sy: e.clientY,
      scaleX: scaleX, scaleY: scaleY,
      cellW: cellW, cellH: cellH, cols: cols, rows: rows,
      ox: g.x, oy: g.y, ow: g.w, oh: g.h,
      moved: false,
    };
    document.body.classList.add("qs-cv-dragging");
    try { widget.setPointerCapture(e.pointerId); } catch (err) {}
    e.preventDefault();
  });

  document.addEventListener("pointermove", function (e) {
    if (!drag) return;
    var dx = (e.clientX - drag.sx) / drag.scaleX;
    var dy = (e.clientY - drag.sy) / drag.scaleY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;

    var L = drag.ox * drag.cellW, T = drag.oy * drag.cellH;
    var W = drag.ow * drag.cellW, H = drag.oh * drag.cellH;
    var minW = drag.cellW, minH = drag.cellH;

    if (drag.mode === "move") {
      L += dx; T += dy;
    } else {
      var h = drag.handle;
      if (h.indexOf("e") >= 0) W = Math.max(minW, W + dx);
      if (h.indexOf("s") >= 0) H = Math.max(minH, H + dy);
      if (h.indexOf("w") >= 0) { W = Math.max(minW, W - dx); L += dx; }
      if (h.indexOf("n") >= 0) { H = Math.max(minH, H - dy); T += dy; }
    }
    var el = drag.el;
    el.style.left = L + "px"; el.style.top = T + "px";
    el.style.width = W + "px"; el.style.height = H + "px";
    el.classList.add("dragging");
  });

  function endDrag(e) {
    if (!drag) return;
    var d = drag; drag = null;
    document.body.classList.remove("qs-cv-dragging");

    if (!d.moved) {
      commit({ action: "select", wid: d.wid });
      return;
    }
    // snap the live pixel box back to grid cells
    var el = d.el;
    var x = Math.round(parseFloat(el.style.left) / d.cellW);
    var y = Math.round(parseFloat(el.style.top) / d.cellH);
    var w = Math.round(parseFloat(el.style.width) / d.cellW);
    var h = Math.round(parseFloat(el.style.height) / d.cellH);
    w = Math.max(1, Math.min(d.cols, w));
    h = Math.max(1, Math.min(d.rows, h));
    x = Math.max(0, Math.min(d.cols - w, x));
    y = Math.max(0, Math.min(d.rows - h, y));
    commit({ action: "geo", wid: d.wid, x: x, y: y, w: w, h: h });
  }

  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);
})();
