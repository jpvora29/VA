/**
 * Setup busy overlay — hold the spinner up for a minimum time.
 *
 * Each Setup callback raises its own flag while it works (`running=` in
 * studio/authoring/setup.py) and the overlay follows all of them at once, so it never
 * lifts early on the fastest one.
 *
 * What this file adds is the DWELL. Against the seed database a filter change is answered
 * in about 95ms, and an overlay that appeared and vanished inside that window read as a
 * blink rather than as progress. CSS cannot express "stay up for at least N ms" — a
 * transition delay only survives while the element is still rendered — so the floor is
 * held here instead: the overlay goes up the instant work starts and comes down either
 * when the work finishes or when the floor expires, whichever is later.
 */
(function () {
  "use strict";

  var MIN_VISIBLE_MS = 320;
  var OVERLAY_ID = "qs-setup-busy";
  var ON = "is-on";

  var raisedAt = 0;
  var timer = null;

  function overlay() {
    return document.getElementById(OVERLAY_ID);
  }

  function raise(el) {
    if (timer) {
      window.clearTimeout(timer);
      timer = null;
    }
    if (!el.classList.contains(ON)) {
      raisedAt = Date.now();
      el.classList.add(ON);
    }
  }

  function lower(el) {
    if (timer) {
      return; // already counting down; a second callback finishing must not restart it
    }
    var held = Date.now() - raisedAt;
    timer = window.setTimeout(function () {
      timer = null;
      el.classList.remove(ON);
    }, Math.max(0, MIN_VISIBLE_MS - held));
  }

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.qsBusy = {
    /**
     * @param {...string} flags one className per Setup callback's busy flag.
     * @returns {*} always no_update — the overlay is driven directly, so Dash has no
     *   output of its own to diff on every keystroke.
     */
    track: function () {
      var el = overlay();
      if (el) {
        var busy = Array.prototype.slice.call(arguments).some(function (cls) {
          return typeof cls === "string" && cls.indexOf("is-busy") !== -1;
        });
        if (busy) {
          raise(el);
        } else {
          lower(el);
        }
      }
      return window.dash_clientside.no_update;
    },
  };
})();
