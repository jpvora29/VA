/*
 * The chat's feel: everything that must happen in the SAME frame as the click.
 *
 * Dash renders the transcript on the server, so every visible change waits for
 * a round trip — and a turn is several of them (store -> render -> launch ->
 * poll). Between a click and the first server response the page used to show
 * nothing at all, which reads as "did it work?". This file closes that gap
 * without taking any state away from Dash:
 *
 *   composer     Enter sends, Shift+Enter breaks the line, the box grows with
 *                the text, Ctrl/Cmd+K focuses it, Esc stops a running turn.
 *   pending      the question appears as a bubble the instant it is sent, and a
 *                "working" card under it narrates each step the analyst takes
 *                (read from the server's own status line, never invented) with
 *                a running clock — the agentic trace a user expects.
 *   switching    New chat / opening a conversation fade the old transcript and
 *                show a skeleton until the server's render lands.
 *   motion       only NEW turns animate in; a re-render or a whole reopened
 *                conversation never replays motion. prefers-reduced-motion off.
 *
 * DOM it adds is appended OUTSIDE the React-managed children lists (after
 * #chat-box inside #chat-viewport, whose own children never change), so React
 * never reconciles it away and never sees it.
 */
(function () {
    "use strict";

    var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var IDLE_LABELS = { "": 1, "Thinking": 1, "Starting…": 1, "Resuming…": 1 };

    function $(id) { return document.getElementById(id); }

    function isVisible(el) {
        if (!el) { return false; }
        var style = window.getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden";
    }

    function thinking() { return isVisible($("stop-btn")); }

    function escapeHtml(text) {
        return String(text == null ? "" : text)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function fmtClock(ms) {
        var s = Math.max(0, ms) / 1000;
        if (s < 60) { return s.toFixed(1) + "s"; }
        var m = Math.floor(s / 60);
        var r = Math.round(s - m * 60);
        return m + "m " + (r < 10 ? "0" : "") + r + "s";
    }

    // ── Toast ────────────────────────────────────────────────────────────────
    var toastTimer = null;
    function toast(text, icon) {
        var el = $("va-toast");
        if (!el) {
            el = document.createElement("div");
            el.id = "va-toast";
            el.className = "va-toast";
            el.setAttribute("role", "status");
            document.body.appendChild(el);
        }
        el.innerHTML = '<i class="bi ' + (icon || "bi-check2-circle") + '"></i><span>' +
            escapeHtml(text) + "</span>";
        el.classList.add("is-on");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { el.classList.remove("is-on"); }, 1800);
    }

    // ── Pending turn: optimistic question + live working card ────────────────
    var pending = null;

    function turnCount(selector) {
        var box = $("chat-box");
        return box ? box.querySelectorAll(selector).length : 0;
    }

    function stepRow(step, index, live) {
        var done = !live;
        return '<li class="va-step' + (done ? " is-done" : " is-live") + '">' +
            '<span class="va-step-mark">' + (done ? '<i class="bi bi-check2"></i>' :
                '<span class="va-spinner"></span>') + "</span>" +
            '<span class="va-step-label">' + escapeHtml(step.label) + "</span>" +
            (done ? '<span class="va-step-time">' + fmtClock(step.ms) + "</span>" : "") +
            "</li>";
    }

    function renderPending() {
        if (!pending) { return; }
        var steps = pending.steps;
        var list = steps.map(function (s, i) { return stepRow(s, i, i === steps.length - 1); }).join("");
        var current = steps.length ? steps[steps.length - 1].label : "Reading your question";
        pending.card.querySelector(".va-work-steps").innerHTML = list;
        pending.card.querySelector(".va-work-title").textContent = current;
    }

    function tick() {
        if (!pending) { return; }
        var clock = pending.card.querySelector(".va-work-clock");
        if (clock) { clock.textContent = fmtClock(performance.now() - pending.t0); }
    }

    function pushStep(label) {
        if (!pending || !label || IDLE_LABELS[label]) { return; }
        var steps = pending.steps;
        var last = steps[steps.length - 1];
        if (last && last.label === label) { return; }
        var now = performance.now();
        if (last) { last.ms = now - last.t; }
        steps.push({ label: label, t: now, ms: 0 });
        renderPending();
    }

    function showPending(question) {
        var viewport = $("chat-viewport");
        var draft = $("live-draft");
        if (!viewport) { return; }
        hideWelcomeInstantly();
        clearPending(true);
        var wrap = document.createElement("div");
        wrap.className = "va-pending" + (REDUCED ? "" : " va-enter");
        var bubble = question ? (
            '<div class="va-pending-user turn turn-user"><div class="message user-message">' +
            '<span class="user-message-text">' + escapeHtml(question) + "</span></div></div>") : "";
        wrap.innerHTML = bubble +
            '<div class="va-work">' +
            '  <div class="va-work-head">' +
            '    <div class="turn-avatar turn-avatar-va va-work-avatar">VA</div>' +
            '    <div class="va-work-main">' +
            '      <div class="va-work-kicker">Virtual Analyst is working<span class="va-dots"><i></i><i></i><i></i></span></div>' +
            '      <div class="va-work-title">Reading your question</div>' +
            "    </div>" +
            '    <span class="va-work-clock">0.0s</span>' +
            "  </div>" +
            '  <ol class="va-work-steps"></ol>' +
            '  <div class="va-work-shimmer"><span></span><span></span><span></span></div>' +
            "</div>";
        if (draft && draft.parentNode === viewport) {
            viewport.insertBefore(wrap, draft);
        } else {
            viewport.appendChild(wrap);
        }
        pending = {
            el: wrap,
            card: wrap.querySelector(".va-work"),
            bubble: wrap.querySelector(".va-pending-user"),
            users: turnCount(".turn-user"),
            answers: turnCount(".turn-assistant"),
            t0: performance.now(),
            steps: [],
            started: false,
            timer: setInterval(tick, 100),
            // If the server never starts a turn (an empty box, a turn already
            // running) the card must not sit there forever.
            guard: setTimeout(function () { if (pending && !pending.started) { clearPending(); } }, 5000),
        };
        var label = ($("thinking-agent") || {}).textContent || "";
        pushStep(IDLE_LABELS[label] ? "Understanding your question" : label);
        viewport.scrollTop = viewport.scrollHeight;
    }

    function clearPending(immediate) {
        if (!pending) { return; }
        var gone = pending;
        pending = null;
        clearInterval(gone.timer);
        clearTimeout(gone.guard);
        // A send that never became a turn (empty box, server refused): the
        // welcome screen comes back rather than leaving a blank page.
        if (realHero() && !document.querySelector("#chat-box .turn")) { showWelcomeAgain(); }
        if (immediate || REDUCED) {
            gone.el.remove();
            return;
        }
        gone.el.classList.add("va-leave");
        setTimeout(function () { gone.el.remove(); }, 180);
    }

    // The welcome screen goes the moment a question is sent. Marked on the
    // VIEWPORT, not on the hero: the hero is a Dash component, and the
    // re-render that follows a send reset its class, so the starters stayed on
    // screen above the question until the answer replaced them.
    function hideWelcomeInstantly() {
        var viewport = $("chat-viewport");
        if (viewport && realHero()) { viewport.classList.add("va-sending"); }
    }

    function showWelcomeAgain() {
        var viewport = $("chat-viewport");
        if (viewport) { viewport.classList.remove("va-sending"); }
    }

    // The run is over but its answer is still being drawn (charts, tables):
    // the card stays, saying so, until the answer is on the page. Removing it
    // when the run ended left the reader looking at their own question for
    // as long as the render took.
    function finishPending() {
        if (!pending) { return; }
        pushStep("Preparing your answer");
        pending.finishing = true;
        clearTimeout(pending.guard);
        pending.guard = setTimeout(function () { clearPending(); }, 15000);
    }

    // The server's status line is the only source of step names.
    function watchStatus() {
        var agent = $("thinking-agent");
        if (!agent || agent.__vaWatched) { return; }
        agent.__vaWatched = true;
        new MutationObserver(function () {
            if (pending) { pushStep((agent.textContent || "").trim()); }
        }).observe(agent, { childList: true, characterData: true, subtree: true });
    }

    function watchThinking() {
        var stop = $("stop-btn");
        if (!stop || stop.__vaWatched) { return; }
        stop.__vaWatched = true;
        var was = thinking();
        new MutationObserver(function () {
            var now = thinking();
            if (now && !was && !(switching && switching.kind === "open")) {
                if (!pending) { showPending(""); }
                pending.started = true;
            }
            if (!now && was) { finishPending(); }
            was = now;
        }).observe(stop, { attributes: true, attributeFilter: ["style", "class"] });
    }

    // ── Composer ─────────────────────────────────────────────────────────────
    function autosize(box) {
        box.style.height = "auto";
        box.style.height = Math.min(box.scrollHeight, 220) + "px";
    }

    function commandMenuOpen() {
        var menu = $("command-menu");
        return menu && menu.style.display !== "none";
    }

    function send(box) {
        var text = (box.value || "").trim();
        var btn = $("send-btn");
        if (!text || !btn || thinking() || btn.disabled) { return false; }
        btn.click();  // the delegated click handler below shows the pending turn
        var composer = box.closest(".composer");
        if (composer) {
            composer.classList.add("is-sending");
            var wait = setInterval(function () {
                if (!box.value) {
                    composer.classList.remove("is-sending");
                    autosize(box);
                    clearInterval(wait);
                }
            }, 40);
            setTimeout(function () { composer.classList.remove("is-sending"); clearInterval(wait); }, 4000);
        }
        return true;
    }

    function wireComposer() {
        var box = $("user-input");
        if (!box || box.__vaWired) { return; }
        box.__vaWired = true;
        box.setAttribute("enterkeyhint", "send");
        box.addEventListener("keydown", function (event) {
            if (event.key !== "Enter" || event.shiftKey || event.isComposing) { return; }
            if (commandMenuOpen()) {
                var first = Array.prototype.find.call(
                    document.querySelectorAll("#command-menu .cmd-item"),
                    function (item) { return item.style.display !== "none"; });
                if (first) { event.preventDefault(); first.click(); }
                return;
            }
            event.preventDefault();
            send(box);
        });
        box.addEventListener("input", function () { autosize(box); });
        autosize(box);
    }

    // ── Switching conversations ──────────────────────────────────────────────
    // Two ways in, one rule: the old transcript is GONE the moment you click.
    //   New chat   instant — a copy of the welcome screen (cached the last time
    //              it was shown) stands in until the server's own arrives, so
    //              the layout, composer included, switches on the click.
    //   Open chat  a skeleton with ONE label, "Loading conversation…", until
    //              the transcript lands. Nothing else: no working card (that is
    //              for a question being answered, not a page being loaded).
    var switchTimer = null;
    var switching = null;      // {kind, from} while a switch is in flight
    var heroCache = null;      // detached copy of the last real welcome hero
    var queuedRef = null;      // a click on the stand-in, replayed on the real one

    function realHero() {
        return document.querySelector("#chat-box .welcome-hero:not(.va-hero-clone)");
    }

    // What the transcript IS, cheaply: how many turns, and whose first question.
    function signature() {
        var box = $("chat-box");
        if (!box) { return ""; }
        var first = box.querySelector(".user-message-text");
        return box.querySelectorAll(".turn").length + "|" +
            (realHero() ? "welcome" : "") + "|" +
            (first ? first.textContent.slice(0, 60) : "");
    }

    // Keep a detached copy of the welcome screen, ids stripped (so the copy
    // never answers a Dash callback) and each control tagged with its position
    // (so a click on the copy can be replayed on the real control).
    function cacheHero() {
        var hero = realHero();
        if (!hero || hero.classList.contains("is-leaving")) { return; }
        var clone = hero.cloneNode(true);
        var real = hero.querySelectorAll("[id]");
        var copies = clone.querySelectorAll("[id]");
        for (var i = 0; i < copies.length; i++) {
            copies[i].removeAttribute("id");
            copies[i].setAttribute("data-va-ref", String(i));
        }
        clone.classList.add("va-hero-clone");
        clone.setAttribute("aria-hidden", "true");
        heroCache = real.length === copies.length ? clone : null;
    }

    function skeleton() {
        return '<div class="va-skel"><span class="va-skel-q"></span>' +
            '<div class="va-skel-card"><span class="w35"></span><span class="w90"></span><span class="w80"></span>' +
            '<span class="w60"></span><span class="w85"></span></div>' +
            '<span class="va-skel-q short"></span></div>';
    }

    function beginSwitch(kind) {
        var viewport = $("chat-viewport");
        var box = $("chat-box");
        if (!viewport || !box) { return; }
        clearPending(true);
        endSwitch(true);
        // Already on an empty chat: the server's render changes nothing.
        if (kind === "new" && realHero() && !box.querySelector(".turn")) { return; }
        switching = { kind: kind, from: signature() };
        viewport.scrollTop = 0;
        clearTimeout(switchTimer);
        switchTimer = setTimeout(function () { endSwitch(); }, 10000);
        if (kind === "new" && heroCache) {
            var stand = heroCache.cloneNode(true);
            box.classList.add("va-instant-new");
            box.appendChild(stand);
            return;
        }
        var overlay = viewport.querySelector(".va-switch");
        if (!overlay) {
            overlay = document.createElement("div");
            overlay.className = "va-switch";
            overlay.setAttribute("role", "status");
            viewport.appendChild(overlay);
        }
        overlay.innerHTML = (kind === "new" ? "" : skeleton()) +
            '<div class="va-switch-label"><span class="va-spinner"></span>' +
            (kind === "new" ? "Starting a new chat…" : "Loading conversation…") + "</div>";
        viewport.classList.add("is-switching");
    }

    function endSwitch(silent) {
        var viewport = $("chat-viewport");
        var box = $("chat-box");
        var was = switching;
        switching = null;
        clearTimeout(switchTimer);
        if (box) {
            box.classList.remove("va-instant-new");
            box.querySelectorAll(".va-hero-clone").forEach(function (el) { el.remove(); });
        }
        if (!viewport) { return; }
        var overlaid = viewport.classList.contains("is-switching");
        viewport.classList.remove("is-switching");
        if (!was || silent) { queuedRef = null; return; }
        // The instant stand-in swaps for the real one with no fade: they look
        // the same, and a fade would read as a flicker.
        if (overlaid && box && !REDUCED) {
            box.classList.remove("va-fade-in");
            void box.offsetWidth;
            box.classList.add("va-fade-in");
        }
        if (queuedRef !== null) {
            var hero = realHero();
            var target = hero && hero.querySelectorAll("[id]")[queuedRef];
            queuedRef = null;
            if (target) { target.click(); }
        }
    }

    function markActive(item) {
        document.querySelectorAll(".conv-item.conv-item-active").forEach(function (el) {
            el.classList.remove("conv-item-active");
        });
        var row = item.closest(".conv-item");
        if (row) { row.classList.add("conv-item-active"); }
    }

    // ── New turns animate in; nothing else does ──────────────────────────────
    function watchTranscript() {
        var box = $("chat-box");
        if (!box || box.__vaWatched) { return; }
        box.__vaWatched = true;
        var turns = box.querySelectorAll(".turn").length;
        var queued = false;
        // Subtree, because a re-render that keeps the same top-level node (the
        // welcome hero, say) only changes what is inside it. Throttled to one
        // pass per frame: a chart's hover layer mutates many times a second.
        new MutationObserver(function () {
            if (queued) { return; }
            queued = true;
            // A timer, not requestAnimationFrame: rAF is paused while the page
            // is in a background tab or pane, which held the loader open.
            setTimeout(function () { queued = false; onTranscriptChange(); }, 16);
        }).observe(box, { childList: true, subtree: true });

        function onTranscriptChange() {
            var all = box.querySelectorAll(".turn");
            var added = all.length - turns;
            if (switching) {
                if (signature() !== switching.from) { endSwitch(); }
            } else if (added > 0 && added <= 2 && !REDUCED) {
                for (var i = all.length - added; i < all.length; i++) {
                    all[i].classList.add("va-enter");
                }
            }
            turns = all.length;
            if (!switching) { cacheHero(); }
            if (pending && pending.bubble && turnCount(".turn-user") > pending.users) {
                pending.bubble.remove();
                pending.bubble = null;
            }
            // The answer was published early while the tail (follow-ups) still
            // runs: the card shrinks to one line under the answer.
            if (pending && turnCount(".turn-assistant") > pending.answers) {
                pending.el.classList.add("is-finishing");
                if (pending.bubble) { pending.bubble.remove(); pending.bubble = null; }
            }
            if (!realHero()) { showWelcomeAgain(); }
            // The answer (or a clarify card, or an error — all assistant turns)
            // is on the page: the working card has done its job.
            if (pending && pending.started && !thinking() &&
                    turnCount(".turn-assistant") > pending.answers) { clearPending(); }
        }
    }

    // ── Lazy evidence charts ─────────────────────────────────────────────────
    // A panel's hidden tabs carry their figure as JSON (ui/components/evidence
    // `_lazy_chart`) and are plotted here the first time they are shown.
    function drawLazyCharts(root, attempt) {
        var pending = Array.prototype.filter.call(
            (root || document).querySelectorAll(".ev-lazy-chart"),
            function (el) { return !el.__vaDrawn && el.offsetParent !== null; });
        if (!pending.length) { return; }
        if (!window.Plotly) {
            // Plotly loads with the first eager graph on the page.
            if ((attempt || 0) < 30) {
                setTimeout(function () { drawLazyCharts(root, (attempt || 0) + 1); }, 100);
            }
            return;
        }
        pending.forEach(function (el) {
            try {
                var figure = JSON.parse(el.getAttribute("data-figure") || "{}");
                el.__vaDrawn = true;
                window.Plotly.newPlot(el, figure.data || [], figure.layout || {},
                    { displayModeBar: false, responsive: true });
            } catch (error) {
                el.__vaDrawn = false;
            }
        });
    }

    // ── Delegated clicks ─────────────────────────────────────────────────────
    document.addEventListener("click", function (event) {
        var target = event.target;
        if (!(target instanceof Element)) { return; }

        var tab = target.closest(".ev-tab, .chart-view-btn");
        if (tab) {
            var panel = tab.closest(".ev-panel") || document;
            // The tab's own clientside callback shows the pane; draw after it.
            setTimeout(function () { drawLazyCharts(panel); }, 30);
            setTimeout(function () { drawLazyCharts(panel); }, 160);
        }

        var stand = target.closest(".va-hero-clone [data-va-ref]");
        if (stand) {
            queuedRef = Number(stand.getAttribute("data-va-ref"));
            return;
        }

        if (target.closest("#stop-btn")) { clearPending(); return; }

        if (target.closest("#new-chat-btn")) { beginSwitch("new"); return; }

        var del = target.closest('[id*="conv-del"]');
        if (del) {
            // Deleting the chat you are reading lands you on a new chat at
            // once (the same instant welcome screen as New chat), rather than
            // leaving the deleted transcript on the page.
            var newChat = $("new-chat-btn");
            if (del.closest(".conv-item-active") && newChat) {
                setTimeout(function () { newChat.click(); }, 0);
            }
            return;
        }
        var conv = target.closest('[id*="conv-item"]');
        if (conv && !conv.closest(".conv-item-active")) {
            markActive(conv);
            beginSwitch("open");
            return;
        }

        var resume = target.closest(".memory-chip-resume");
        if (resume) {
            var id = resume.getAttribute("data-conv");
            var match = Array.prototype.find.call(
                document.querySelectorAll('[id*="conv-item"]'),
                function (el) { return el.id.indexOf('"' + id + '"') !== -1; });
            if (match) { match.click(); }
            return;
        }

        var chip = target.closest('[id*="suggestion-chip"]');
        if (chip && !thinking()) {
            var text = chip.getAttribute("title") || "";
            showPending(text.replace(/^Ask:\s*/, ""));
            return;
        }

        if (target.closest('[id*="starter-chip"]')) {
            var box = $("user-input");
            setTimeout(function () {
                if (!box) { return; }
                box.focus();
                box.setSelectionRange(box.value.length, box.value.length);
                autosize(box);
                var composer = box.closest(".composer");
                if (composer && !REDUCED) {
                    composer.classList.remove("va-pulse");
                    void composer.offsetWidth;
                    composer.classList.add("va-pulse");
                }
            }, 90);
            return;
        }

        if (target.closest("#send-btn")) {
            var input = $("user-input");
            if (input && (input.value || "").trim() && !thinking()) { showPending(input.value.trim()); }
            return;
        }

        if (target.closest(".answer-copy, .user-copy")) { toast("Copied to clipboard"); }
    }, true);

    // ── Global shortcuts ─────────────────────────────────────────────────────
    function typingIn(target) {
        if (!(target instanceof Element)) { return false; }
        // The composer right after sending is focused but empty: a digit there
        // is an answer to the card, not the start of a new question.
        if (target.id === "user-input" && !(target.value || "").trim()) { return false; }
        return !!(target.closest("input, textarea, select") || target.isContentEditable);
    }

    document.addEventListener("keydown", function (event) {
        // A clarification card is open: 1-9 picks an option, like a CLI prompt.
        var cards = document.querySelectorAll("#chat-box .clarify-v2");
        var card = cards.length ? cards[cards.length - 1] : null;
        if (card && /^[1-9]$/.test(event.key) && !typingIn(event.target) &&
                !event.ctrlKey && !event.metaKey && !event.altKey) {
            var option = card.querySelector('.clarify-option[data-key="' + event.key + '"]');
            if (option) { event.preventDefault(); option.click(); return; }
        }
        // Enter in "something else" sends it (the input only commits its value
        // on Enter/blur, so the click waits a tick for that commit to land).
        if (event.key === "Enter" && event.target instanceof Element &&
                event.target.classList.contains("clarify-free-input")) {
            var group = event.target.closest(".clarify-free-group");
            var submit = group && group.querySelector(".clarify-free-submit");
            if (submit) { setTimeout(function () { submit.click(); }, 80); }
            return;
        }
        var box = $("user-input");
        if (!box || !isVisible(box)) { return; }
        // Shift+Esc focuses the composer (Ctrl+K searches the chat list —
        // assets/chat_sidebar.js).
        if (event.key === "Escape" && event.shiftKey) {
            event.preventDefault();
            box.focus();
            return;
        }
        if (event.key === "Escape" && thinking()) {
            var stop = $("stop-btn");
            if (stop) { stop.click(); toast("Stopping…", "bi-stop-circle"); }
        }
    });

    // The chat mounts after sign-in, and parts re-mount; wire whatever exists.
    function scan() {
        wireComposer();
        watchStatus();
        watchThinking();
        watchTranscript();
        if (!heroCache && !switching) { cacheHero(); }
    }
    new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", scan);
    } else {
        scan();
    }

    window.vaChat = { showPending: showPending, clearPending: clearPending, toast: toast,
                      beginSwitch: beginSwitch, endSwitch: endSwitch };
})();
