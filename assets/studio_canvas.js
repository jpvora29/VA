/* Boardroom Canvas direct manipulation — move, resize, select, and retype text.
   The canvas surface owns all pointer interaction; on drop it writes the result
   to the hidden #qs-cv-sink input, which a Dash callback commits to the shared
   document. Text nodes carrying data-qs-path are contentEditable: the user types
   straight on the slide and the new text goes down the same sink on blur.
   Event delegation on `document` so it survives Dash re-renders. */
(function () {
  "use strict";

  var EDITABLE = "[data-qs-path]";
  var POINT_PATH = /^points\.(\d+)\.text$/;

  var drag = null;
  var pendingFocus = null;

  function surface() { return document.getElementById("qs-cv-surface"); }

  function closest(node, selector) {
    return node && node.closest ? node.closest(selector) : null;
  }

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

  /* ── move / resize ───────────────────────────────────────────────────────── */

  document.addEventListener("pointerdown", function (e) {
    var s = surface();
    if (!s) return;
    var widget = closest(e.target, ".qs-cv-widget");
    if (!widget || !s.contains(widget)) return;
    // A click on editable text places the caret instead of starting a drag.
    if (closest(e.target, EDITABLE)) return;

    var rect = s.getBoundingClientRect();
    var cols = parseInt(s.getAttribute("data-cols"), 10) || 12;
    var rows = parseInt(s.getAttribute("data-rows"), 10) || 8;
    var scaleX = rect.width / (s.offsetWidth || rect.width);
    var scaleY = rect.height / (s.offsetHeight || rect.height);
    var cellW = (s.offsetWidth || rect.width) / cols;
    var cellH = (s.offsetHeight || rect.height) / rows;
    var handle = closest(e.target, ".qs-cv-handle");
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

  /* ── inline text editing ─────────────────────────────────────────────────── */

  function normalize(text) {
    return String(text == null ? "" : text).replace(/\s+/g, " ").trim();
  }

  function caretToEnd(el) {
    var range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  /* Dash re-renders the slide after every commit, so the node to focus next does
     not exist yet. Watch for it, then put the caret in it. */
  function focusWhenReady(wid, path) {
    pendingFocus = { wid: wid, path: path, until: Date.now() + 3000 };
    requestAnimationFrame(tryPendingFocus);
  }

  function tryPendingFocus() {
    if (!pendingFocus) return;
    var el = document.querySelector(
      '[data-qs-wid="' + pendingFocus.wid + '"][data-qs-path="' + pendingFocus.path + '"]'
    );
    if (el) {
      pendingFocus = null;
      el.focus();
      caretToEnd(el);
      return;
    }
    if (Date.now() > pendingFocus.until) { pendingFocus = null; return; }
    requestAnimationFrame(tryPendingFocus);
  }

  document.addEventListener("focusin", function (e) {
    var el = closest(e.target, EDITABLE);
    if (el) el.setAttribute("data-qs-original", el.textContent);
  });

  document.addEventListener("focusout", function (e) {
    var el = closest(e.target, EDITABLE);
    if (!el) return;
    var original = el.getAttribute("data-qs-original");
    var then = el.getAttribute("data-qs-then") || "";
    el.removeAttribute("data-qs-original");
    el.removeAttribute("data-qs-then");
    if (original === null) return;
    var value = normalize(el.textContent);
    if (!then && value === normalize(original)) return;
    commit({
      action: "text",
      wid: el.getAttribute("data-qs-wid"),
      path: el.getAttribute("data-qs-path"),
      value: value,
      then: then,
    });
  });

  document.addEventListener("keydown", function (e) {
    var el = closest(e.target, EDITABLE);
    if (!el) return;
    if (e.key === "Escape") {
      e.preventDefault();
      el.textContent = el.getAttribute("data-qs-original") || "";
      el.removeAttribute("data-qs-original");
      el.removeAttribute("data-qs-then");
      el.blur();
      return;
    }
    if (e.key !== "Enter" || e.shiftKey) return;
    e.preventDefault();
    // Enter inside a commentary bullet starts the next bullet; everywhere else
    // it simply ends the edit, because a slide text box is one line of prose.
    var point = POINT_PATH.exec(el.getAttribute("data-qs-path") || "");
    if (point && normalize(el.textContent)) {
      el.setAttribute("data-qs-then", "point-add");
      focusWhenReady(
        el.getAttribute("data-qs-wid"),
        "points." + (Number(point[1]) + 1) + ".text"
      );
    }
    el.blur();
  });

  /* Paste plain text only — a slide never wants the source page's markup. */
  document.addEventListener("paste", function (e) {
    var el = closest(e.target, EDITABLE);
    if (!el || !e.clipboardData) return;
    e.preventDefault();
    var text = normalize(e.clipboardData.getData("text/plain"));
    document.execCommand("insertText", false, text);
  });
})();
