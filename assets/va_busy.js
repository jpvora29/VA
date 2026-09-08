/**
 * Busy overlays — show one only when the wait is real, then hold it long enough to read.
 *
 * Each callback that can make the user wait raises its own flag (`running=` via
 * ui/shell/busy.py) and an overlay follows all of its scope's flags at once, so it never
 * lifts early on the fastest one.
 *
 * Three things live here that CSS cannot express, because a transition only survives
 * while the element is still rendered:
 *
 *   * GRACE — a flag may declare `data-grace`, a number of milliseconds of work to
 *     tolerate before the overlay appears at all. Dash re-runs a callback whenever the
 *     component carrying its Input is MOUNTED, not only when someone acts: Studio
 *     renders its whole body from a callback, so every mode switch re-fires the Data
 *     page's handlers, Export's, and Setup's cascade. Measured on the real page those
 *     answer `no_update` in 33-90ms, well inside a grace, so they cost nothing — while a
 *     mode switch that genuinely takes a second still shows.
 *   * DWELL — once up, the overlay stays up for a floor. Against the seed database a
 *     filter change is answered in about 95ms, and an overlay that appeared and vanished
 *     inside that window read as a blink rather than as progress.
 *   * LABEL — each flag carries a `data-label` naming what it is doing.
 *
 * The label and the grace are both taken from the flag that STARTED the busy period,
 * not from whatever happens to be busy when the overlay paints. That distinction is the
 * whole difference between a useful cue and a misleading one: a mode switch runs render
 * first and then re-fires four mounted callbacks behind it, so reading the label late
 * announced "Building your PowerPoint…" to somebody who had clicked Setup.
 *
 * One tracker serves every scope (Studio, and the shell above it), so per-overlay state
 * is keyed by overlay id rather than held in a module variable.
 */
(function () {
  "use strict";

  var MIN_VISIBLE_MS = 320;
  var ON = "is-on";
  var FLAG = ".va-busy-flag";

  /** overlay id -> { shownAt, showTimer, hideTimer, label } */
  var state = {};

  function slot(id) {
    if (!state[id]) {
      state[id] = { shownAt: 0, showTimer: null, hideTimer: null, label: "" };
    }
    return state[id];
  }

  /**
   * The first flag of this scope that is busy, as `{label, grace}`.
   *
   * Read from the callback's own arguments rather than from the DOM: they arrive in the
   * order the flags were declared (ui/shell/busy.py builds both lists from one tuple),
   * which is the order the flag elements sit in, and they are the values Dash is
   * applying — so this cannot disagree with the reason the tracker was called.
   */
  function starter(args, el) {
    var flags = el.parentNode ? el.parentNode.querySelectorAll(FLAG) : [];
    var n = Math.min(args.length, flags.length);
    for (var i = 0; i < n; i++) {
      if (typeof args[i] === "string" && args[i].indexOf("is-busy") !== -1) {
        return {
          label: flags[i].getAttribute("data-label") || "",
          grace: parseInt(flags[i].getAttribute("data-grace") || "0", 10) || 0,
        };
      }
    }
    return null;
  }

  function show(el) {
    var s = slot(el.id);
    var node = document.getElementById(el.id + "-label");
    if (node) {
      node.textContent = s.label;
    }
    s.shownAt = Date.now();
    el.classList.add(ON);
  }

  function raise(el, args) {
    var s = slot(el.id);
    if (s.hideTimer) {
      window.clearTimeout(s.hideTimer);
      s.hideTimer = null;
    }
    if (el.classList.contains(ON) || s.showTimer) {
      return; // already up, or already counting down to it — this period has its label
    }
    var first = starter(args, el);
    if (!first) {
      return;
    }
    s.label = first.label;
    if (first.grace <= 0) {
      show(el);
      return;
    }
    s.showTimer = window.setTimeout(function () {
      s.showTimer = null;
      show(el);
    }, first.grace);
  }

  function lower(el) {
    var s = slot(el.id);
    if (s.showTimer) {
      // The work finished inside its grace: nothing was ever shown, so nothing to hide.
      window.clearTimeout(s.showTimer);
      s.showTimer = null;
      return;
    }
    if (s.hideTimer || !el.classList.contains(ON)) {
      return; // already counting down; a second callback finishing must not restart it
    }
    var held = Date.now() - s.shownAt;
    s.hideTimer = window.setTimeout(function () {
      s.hideTimer = null;
      el.classList.remove(ON);
    }, Math.max(0, MIN_VISIBLE_MS - held));
  }

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.vaBusy = {
    /**
     * @param {...string} args one className per flag in the scope, in declaration
     *   order, then the overlay id (passed as State so one function serves every scope).
     * @returns {*} always no_update — the overlay is driven directly, so Dash has no
     *   output of its own to diff on every keystroke.
     */
    track: function () {
      var args = Array.prototype.slice.call(arguments);
      var overlayId = args.pop();
      var el = overlayId ? document.getElementById(overlayId) : null;
      if (el) {
        var busy = args.some(function (cls) {
          return typeof cls === "string" && cls.indexOf("is-busy") !== -1;
        });
        if (busy) {
          raise(el, args);
        } else {
          lower(el);
        }
      }
      return window.dash_clientside.no_update;
    },
  };
})();
