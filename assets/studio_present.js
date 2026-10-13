/* Studio Present — paging through the slideshow (studio/page/authoring/present.py).
 *
 * The server lays every page into the show and marks one `is-current`; everything after
 * that happens here, so a page turn never waits on a round trip:
 *   → ↓ PageDown Space Enter   next page        ← ↑ PageUp Backspace   previous page
 *   Home / End                 first / last     Esc                    end the show
 *   click the right / left half of the screen   next / previous
 * Clicking Present also asks the browser for full screen. That request has to be made
 * inside the click itself, before the server has answered, so it lives here. Leaving
 * full screen (the browser's own Esc) ends the show too.
 * Listeners are delegated on the document: Dash replaces subtrees and would drop any
 * listener bound to a node.
 */
(function () {
    "use strict";

    var NEXT = ["ArrowRight", "ArrowDown", "PageDown", " ", "Enter"];
    var PREV = ["ArrowLeft", "ArrowUp", "PageUp", "Backspace"];

    function showRoot() { return document.querySelector(".qs-present"); }

    function pages(root) { return root.querySelectorAll(".qs-present-slide"); }

    function currentPage(list) {
        for (var i = 0; i < list.length; i++) {
            if (list[i].classList.contains("is-current")) { return i; }
        }
        return 0;
    }

    function goTo(root, target) {
        var list = pages(root);
        if (!list.length) { return; }
        var next = Math.max(0, Math.min(list.length - 1, target));
        var now = currentPage(list);
        if (next === now) { return; }
        list[now].classList.remove("is-current");
        list[next].classList.add("is-current");
    }

    function step(root, delta) { goTo(root, currentPage(pages(root)) + delta); }

    function leaveFullscreen() {
        if (document.fullscreenElement && document.exitFullscreen) {
            document.exitFullscreen().catch(function () {});
        }
    }

    // Ending goes through the close button, so the server takes the show down; the flag
    // stops the full-screen exit this causes from pressing it a second time.
    function endShow(root) {
        if (root.getAttribute("data-ending")) { return; }
        root.setAttribute("data-ending", "1");
        var close = root.querySelector(".qs-present-close");
        if (close) { close.click(); }
        leaveFullscreen();
    }

    document.addEventListener("click", function (event) {
        var t = event.target;
        if (!t.closest) { return; }
        var open = t.closest(".qs-present-open");
        if (open && !open.disabled && !document.fullscreenElement &&
                document.documentElement.requestFullscreen) {
            document.documentElement.requestFullscreen().catch(function () {});
            return;
        }
        var root = showRoot();
        if (root && t.closest(".qs-present-close")) {
            root.setAttribute("data-ending", "1");
            leaveFullscreen();
            return;
        }
        var stage = t.closest(".qs-present-stage");
        if (!root || !stage || !root.contains(stage)) { return; }
        var box = stage.getBoundingClientRect();
        step(root, event.clientX < box.left + box.width / 2 ? -1 : 1);
    });

    // Capture phase: while the show is up, its keys must not also reach the canvas below.
    document.addEventListener("keydown", function (event) {
        var root = showRoot();
        if (!root || event.ctrlKey || event.metaKey || event.altKey) { return; }
        var key = event.key;
        if (NEXT.indexOf(key) !== -1) {
            step(root, 1);
        } else if (PREV.indexOf(key) !== -1) {
            step(root, -1);
        } else if (key === "Home") {
            goTo(root, 0);
        } else if (key === "End") {
            goTo(root, pages(root).length - 1);
        } else if (key === "Escape") {
            endShow(root);
        } else {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
    }, true);

    document.addEventListener("fullscreenchange", function () {
        if (document.fullscreenElement) { return; }
        var root = showRoot();
        if (root) { endShow(root); }
    });
})();
