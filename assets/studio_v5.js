/* Studio v5 — interaction feedback that must not wait for a server round trip.
 *
 * Everything here is presentation only: event delegation on the document (Dash re-renders
 * whole subtrees, so listeners bound to nodes would be lost), classes added and removed,
 * no Dash props written. Motion is skipped for people who ask their OS for less of it.
 */
(function () {
    "use strict";

    var reduceMotion = window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function restart(el, cls, ms) {
        if (!el) { return; }
        el.classList.remove(cls);
        // Force a reflow so the animation replays on a second click of the same element.
        void el.offsetWidth;
        el.classList.add(cls);
        window.setTimeout(function () { el.classList.remove(cls); }, ms);
    }

    /* 1. Canvas text boxes and table cells: a tactile tap, then nothing left behind.
     *    The edit panel beside the slide flashes so the eye follows the words there. */
    document.addEventListener("pointerdown", function (event) {
        var pick = event.target.closest && event.target.closest(".qs-tf-pick");
        if (!pick || pick.closest(".qs7-canvas")) { return; }   // the focus canvas holds still
        if (navigator.vibrate && event.pointerType === "touch") {
            try { navigator.vibrate(8); } catch (e) { /* not allowed: fine */ }
        }
        if (reduceMotion) { return; }
        restart(pick, "qs-tap", 520);
        var box = pick.parentElement;
        restart(box, "qs-tapped", 520);
    }, true);

    // The click must not leave a focus ring on the slide: focus moves to the editor.
    document.addEventListener("click", function (event) {
        var pick = event.target.closest && event.target.closest(".qs-tf-pick");
        if (!pick) { return; }
        window.setTimeout(function () {
            pick.blur();
            if (!reduceMotion) {
                restart(document.querySelector("#qs-tf-editor .qs-tf-te"), "qs-flash", 900);
            }
        }, 60);
    }, true);

    /* 2. The Setup preview: a figure that changed lands with a short rise, so the eye
     *    sees WHICH tile moved when a filter changes. Watches the whole document because
     *    the preview panel is re-created whenever Setup is re-rendered. */
    var lastValues = {};
    function markChanged(root) {
        var tiles = (root || document).querySelectorAll("#studio-scope-preview .qs-prev-tile");
        tiles.forEach(function (tile) {
            var label = tile.querySelector(".qs-prev-label");
            var value = tile.querySelector(".qs-prev-value");
            if (!label || !value) { return; }
            var key = label.textContent, text = value.textContent;
            if (lastValues[key] !== undefined && lastValues[key] !== text && !reduceMotion) {
                restart(value, "qs-changed", 560);
            }
            lastValues[key] = text;
        });
    }
    new MutationObserver(function (mutations) {
        for (var i = 0; i < mutations.length; i++) {
            var t = mutations[i].target;
            if (t && t.closest && t.closest("#studio-scope-preview")) { markChanged(); return; }
        }
    }).observe(document.documentElement, {childList: true, subtree: true, characterData: true});

    /* 3. The canvas slide fits the width it is given. The surface is laid out at the
     *    preview's own pixel size (the click targets are positioned in it), so it is
     *    SCALED rather than re-laid-out — a CSS transform scales hit-testing too, so every
     *    click still lands on the box under the pointer. Margins make the layout box match
     *    the scaled one so the page below it moves up or down with it. */
    function fitStage(stage) {
        var surface = stage.querySelector(":scope > .qs-tf-surface");
        if (!surface) { return; }
        var baseW = surface.offsetWidth, baseH = surface.offsetHeight;
        if (!baseW) { return; }
        var cs = window.getComputedStyle(stage);
        var avail = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        var scale = Math.max(0.5, Math.min(1.6, avail / baseW));
        // The focus canvas (studio_v6) shows the WHOLE slide: never taller than the visible
        // canvas area. Measured from the scroll host alone — not from panels around the
        // slide — so opening an editor or a panel can never resize (and jolt) the slide.
        var host = stage.closest(".qs7-canvas") && stage.closest(".qs-canvas-host");
        if (host) {
            var hs = window.getComputedStyle(host);
            var room = host.clientHeight - parseFloat(hs.paddingTop) - 36 - 12;  // wrap padding
            if (room > 200) { scale = Math.max(0.35, Math.min(scale, room / baseH)); }
        }
        surface.style.transform = "scale(" + scale.toFixed(4) + ")";
        surface.style.marginRight = (baseW * (scale - 1)).toFixed(1) + "px";
        surface.style.marginBottom = (baseH * (scale - 1)).toFixed(1) + "px";
        stage.classList.add("qs-fitted");
    }
    var watched = new WeakSet();
    var resizer = window.ResizeObserver ? new ResizeObserver(function (entries) {
        entries.forEach(function (entry) { fitStage(entry.target); });
    }) : null;
    function adoptStages() {
        document.querySelectorAll(".qs-tf-stage").forEach(function (stage) {
            if (!watched.has(stage)) {
                watched.add(stage);
                if (resizer) { resizer.observe(stage); }
            }
            fitStage(stage);
        });
        var current = document.querySelector(".qs-tf-strip .qs-strip-thumb.is-current");
        if (current && !current.dataset.qsShown) {
            current.dataset.qsShown = "1";
            // Scroll the STRIP sideways only. scrollIntoView also scrolled the canvas down
            // to the strip, which left the top of the slide off screen.
            var strip = current.closest(".qs-tf-strip");
            if (strip) {
                var left = current.offsetLeft - (strip.clientWidth - current.offsetWidth) / 2;
                strip.scrollTo({left: Math.max(0, left), behavior: reduceMotion ? "auto" : "smooth"});
            }
        }
    }
    var pending = false;
    new MutationObserver(function () {
        if (pending) { return; }
        pending = true;
        window.requestAnimationFrame(function () { pending = false; adoptStages(); });
    }).observe(document.documentElement, {childList: true, subtree: true});
    window.addEventListener("resize", adoptStages);

    /* 4. Buttons: a soft press ripple at the pointer, the way a native app answers a tap. */
    var RIPPLE = ".qs-generate-btn, .qs-tf-addbtn, .qs-mode-btn, .qs-col-addbtn, " +
                 ".qs-map-submit, .qs-ds-use, .qs-v5-ripple";
    document.addEventListener("pointerdown", function (event) {
        if (reduceMotion) { return; }
        var btn = event.target.closest && event.target.closest(RIPPLE);
        if (!btn || btn.disabled) { return; }
        var rect = btn.getBoundingClientRect();
        var size = Math.max(rect.width, rect.height) * 1.6;
        var dot = document.createElement("span");
        dot.className = "qs-ripple";
        dot.style.width = dot.style.height = size + "px";
        dot.style.left = (event.clientX - rect.left - size / 2) + "px";
        dot.style.top = (event.clientY - rect.top - size / 2) + "px";
        btn.appendChild(dot);
        window.setTimeout(function () { dot.remove(); }, 650);
    }, true);
})();
