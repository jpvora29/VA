/* The Chatbot rail's browser-side behaviour (ui/components/sidebar.py).

   Three small jobs, none of which needs the server:
     1. the search box filters the chat list by title, and keeps filtering
        after the list is redrawn (a turn commits, a chat is pinned);
     2. Ctrl/Cmd+K jumps to that box from anywhere in the Chatbot, opening a
        collapsed rail first;
     3. a [data-click] button forwards its click to the element it names (the
        help card's "Take the tour" -> the navbar's tour button).
*/
(function () {
    "use strict";

    function searchBox() { return document.getElementById("conv-search"); }

    function filterList() {
        var box = searchBox();
        var list = document.getElementById("conversation-list");
        if (!box || !list) { return; }
        var query = (box.value || "").trim().toLowerCase();
        var shown = 0;
        list.querySelectorAll(".conv-group").forEach(function (group) {
            var visible = 0;
            group.querySelectorAll(".conv-item").forEach(function (row) {
                var hit = !query || (row.getAttribute("data-title") || "").indexOf(query) !== -1;
                row.hidden = !hit;
                if (hit) { visible += 1; }
            });
            group.hidden = visible === 0;
            shown += visible;
        });
        var rail = list.closest(".app-sidebar");
        if (rail) { rail.classList.toggle("is-search-empty", !!query && shown === 0); }
    }

    document.addEventListener("input", function (event) {
        if (event.target && event.target.id === "conv-search") { filterList(); }
    });

    // Esc in the box clears the search before anything else sees the key.
    document.addEventListener("keydown", function (event) {
        var box = searchBox();
        if (event.key === "Escape" && box && event.target === box && box.value) {
            event.stopPropagation();
            // Through the native setter + an input event, so dcc.Input's React
            // state clears too; a bare `box.value = ""` comes back on re-render.
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(box, "");
            box.dispatchEvent(new Event("input", { bubbles: true }));
            return;
        }
        if (!(event.ctrlKey || event.metaKey) || (event.key !== "k" && event.key !== "K")) { return; }
        var rail = box && box.closest(".app-sidebar");
        if (!rail || !rail.offsetParent) { return; }  // the Chatbot pane is not on screen
        event.preventDefault();
        if (!railCollapsed()) {
            box.focus();
            box.select();
            return;
        }
        var toggle = rail.querySelector(".va-rail-toggle");
        if (toggle) { toggle.click(); }
        // The rail widens on a transition; focus once the box is displayed.
        setTimeout(function () { box.focus(); box.select(); }, 60);
    }, true);

    // ── Row "..." menu ───────────────────────────────────────────────────────
    // Opened by an explicit click, not by :focus-within. Safari (and Firefox on
    // macOS) never focus a button that is clicked, so a focus-driven menu simply
    // never opened there — Pin and Delete were unreachable.
    function closeMenus(except) {
        document.querySelectorAll(".app-sidebar .conv-item-actions.is-open").forEach(function (el) {
            if (el !== except) { el.classList.remove("is-open"); }
        });
    }

    function openMenu(actions) {
        // A row near the foot of the rail would open below the fold: flip it up.
        var body = actions.closest(".va-rail-body");
        if (body) {
            var room = body.getBoundingClientRect().bottom - actions.getBoundingClientRect().bottom;
            actions.classList.toggle("opens-up", room < 96);
        }
        closeMenus(actions);
        actions.classList.add("is-open");
    }

    document.addEventListener("click", function (event) {
        var target = event.target instanceof Element ? event.target : null;
        if (!target) { return; }
        var more = target.closest(".app-sidebar .conv-item-more");
        if (more) {
            var actions = more.closest(".conv-item-actions");
            if (actions.classList.contains("is-open")) {
                actions.classList.remove("is-open");
            } else {
                openMenu(actions);
            }
            return;
        }
        // Choosing an item closes the menu once its own click has run; a
        // click anywhere else closes it at once.
        if (target.closest(".app-sidebar .conv-menu")) {
            setTimeout(function () { closeMenus(); }, 0);
            return;
        }
        closeMenus();
    }, true);

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") { closeMenus(); }
    });

    function railCollapsed() { return !!document.querySelector(".va-rails-collapsed .app-sidebar"); }

    document.addEventListener("click", function (event) {
        // Collapsed, the help card has no room: open the rail, then the card.
        var help = event.target instanceof Element && event.target.closest(".app-sidebar .help-toggle");
        if (help && railCollapsed()) {
            var toggle = help.closest(".app-sidebar").querySelector(".va-rail-toggle");
            if (toggle) { toggle.click(); }
            setTimeout(function () { help.focus(); }, 60);
            return;
        }
        var source = event.target instanceof Element && event.target.closest("[data-click]");
        if (!source) { return; }
        var target = document.getElementById(source.getAttribute("data-click"));
        if (target) {
            source.blur();
            target.click();
        }
    });

    // The list is replaced wholesale on every refresh; re-apply the filter.
    function watchList() {
        var list = document.getElementById("conversation-list");
        if (!list || list.__vaFiltered) { return; }
        list.__vaFiltered = true;
        new MutationObserver(filterList).observe(list, { childList: true });
    }
    new MutationObserver(watchList).observe(document.documentElement, { childList: true, subtree: true });
    watchList();
})();
