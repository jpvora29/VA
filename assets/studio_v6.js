/* Studio v6 — the editorial Setup and the focus canvas.
 *
 * Two kinds of code live here:
 *   1. dash_clientside.qs6.* — clientside callbacks registered from Python
 *      (studio/authoring/setup_summary.py). They turn values already in the browser into
 *      text, so the cover follows every pick without a server round trip.
 *   2. Presentation-only behaviour: the month popover opening and closing, text that
 *      changes with a short cross-fade. Event delegation on the document, because Dash
 *      re-renders whole subtrees and a listener bound to a node would be lost.
 * Motion is skipped for people who ask their OS for less of it.
 */
(function () {
    "use strict";

    var reduceMotion = window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

    function listed(value) {
        if (value === null || value === undefined || value === "") { return []; }
        var values = Array.isArray(value) ? value : [value];
        return values.filter(function (v) {
            return v !== null && v !== undefined && String(v).trim() !== "" &&
                String(v).toLowerCase() !== "all";
        }).map(String);
    }

    function monthOf(iso) {
        var m = /^(\d{4})-(\d{2})/.exec(String(iso || ""));
        return m ? {y: +m[1], m: +m[2]} : null;
    }

    function monthLabel(mo) { return MONTHS[mo.m - 1] + " " + mo.y; }

    function periodText(get, basis, dates) {
        dates = dates || {};
        var from = monthOf(dates.from), to = monthOf(dates.to);
        var name = basis === "r12m" ? "R12M" : "YTD";
        if (dates.custom && from && to) {
            return (from.y === to.y ? MONTHS[from.m - 1] : monthLabel(from)) +
                " – " + monthLabel(to);
        }
        if (to) { return name + " " + monthLabel(to); }
        var years = listed(get("year")).map(Number).filter(function (y) { return !isNaN(y); });
        var year = years.length ? Math.max.apply(null, years) : null;
        var quarters = listed(get("quarter"));
        if (quarters.length) {
            return quarters.join(", ") + (year ? " " + year : "");
        }
        return name + (year ? " " + year : " · latest");
    }

    function scopeText(get) {
        var markets = listed(get("country"));
        var lines = listed(get("product_line"));
        var parts = [];
        parts.push(markets.length > 2 ? markets.length + " markets"
                   : (markets.length ? markets.join(" · ") : "All markets"));
        if (lines.length) {
            parts.push(lines.length > 2 ? lines.length + " product lines" : lines.join(" · "));
        }
        return parts.join("   |   ");
    }

    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.qs6 = {
        paintCover: function (values, basis, dates, ids) {
            var byCol = {};
            (ids || []).forEach(function (id, i) { byCol[id.col] = (values || [])[i]; });
            var get = function (col) { return byCol[col]; };
            var carrier = listed(get("carrier"))[0] || "Choose a carrier";
            return [carrier, periodText(get, basis, dates), scopeText(get)];
        }
    };

    /* ── the month popover ─────────────────────────────────────────────────── */

    var rangeClicks = 0;

    function wrapOf(el) { return el && el.closest && el.closest(".qs6-month-wrap"); }

    function closeAll(except) {
        document.querySelectorAll(".qs6-month-wrap.is-open").forEach(function (w) {
            if (w !== except) { w.classList.remove("is-open"); }
        });
    }

    function inRangeMode(wrap) {
        var on = wrap && wrap.querySelector(".qs6-pmode.is-on");
        return !!(on && on.id && on.id.indexOf('"range"') !== -1);
    }

    function closeSoon(wrap) {
        // Long enough for the pick to paint in the grid before it folds away.
        window.setTimeout(function () { wrap.classList.remove("is-open"); }, reduceMotion ? 0 : 180);
    }

    document.addEventListener("click", function (event) {
        var t = event.target;
        var trigger = t.closest && t.closest("#qs6-month-trigger");
        if (trigger) {
            var wrap = wrapOf(trigger);
            closeAll(wrap);
            rangeClicks = 0;
            wrap.classList.toggle("is-open");
            return;
        }
        var wrapIn = wrapOf(t);
        if (!wrapIn) { closeAll(null); return; }
        if (t.closest(".qs6-pmode")) { rangeClicks = 0; return; }
        if (t.closest(".qs6-preset")) { closeSoon(wrapIn); return; }
        var month = t.closest(".qs6-month");
        if (month && !month.disabled) {
            if (inRangeMode(wrapIn)) {
                rangeClicks += 1;
                if (rangeClicks % 2 === 0) { closeSoon(wrapIn); }
            } else {
                closeSoon(wrapIn);
            }
        }
    }, true);

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") { closeAll(null); }
    });

    /* ── the page list's hover preview sits beside the aside, level with its row ── */

    document.addEventListener("mouseover", function (event) {
        var row = event.target.closest && event.target.closest(".qs6-contents-card .qs-slide-row");
        if (!row) { return; }
        var pop = row.querySelector(".qs-slide-pop");
        var aside = row.closest(".qs6-aside");
        if (!pop || !aside) { return; }
        var box = aside.getBoundingClientRect(), r = row.getBoundingClientRect();
        var width = Math.min(440, Math.max(280, box.left - 40));
        var half = (width * 9 / 16 + 44) / 2;          // the card's rendered half-height
        var mid = Math.max(half + 12, Math.min(window.innerHeight - half - 12, r.top + r.height / 2));
        pop.style.width = width + "px";
        pop.style.left = Math.max(12, box.left - width - 18) + "px";
        pop.style.right = "auto";
        pop.style.top = mid + "px";
    });

    /* ── the canvas: live preview, Apply, and the retype ───────────────────── */

    function barOf(el) { return el && el.closest && el.closest(".qs7-editbar[data-at]"); }

    function boxFor(key) {
        if (!key) { return null; }
        return document.querySelector('.qs-tf-surface [data-at="' + key + '"]');
    }

    function typedLines(bar) {
        var out = [];
        bar.querySelectorAll(".qs7-ln-input").forEach(function (area) {
            String(area.value || "").split(/\n/).forEach(function (line) {
                if (line.trim()) { out.push(line.trim()); }
            });
        });
        return out;
    }

    function autoGrow(area) {
        area.style.height = "auto";
        area.style.height = Math.min(area.scrollHeight + 2, 220) + "px";
    }

    // The words the author is typing, drawn over the box on the slide right away.
    function preview(bar) {
        var box = boxFor(bar.getAttribute("data-at"));
        if (!box) { return; }
        var live = box.querySelector(":scope > .qs7-live");
        if (!live) {
            live = document.createElement("div");
            live.className = "qs-tf-reflect qs7-live";
            box.appendChild(live);
        }
        live.innerHTML = "";
        typedLines(bar).forEach(function (line) {
            var row = document.createElement("div");
            row.className = "qs-tf-reflect-line";
            row.textContent = line;
            live.appendChild(row);
        });
        box.classList.add("is-previewing");
    }

    function dropPreview(bar) {
        var box = boxFor(bar && bar.getAttribute("data-at"));
        if (!box) { return; }
        var live = box.querySelector(":scope > .qs7-live");
        if (live) { live.remove(); }
        box.classList.remove("is-previewing");
    }

    function isDirty(bar) { return !!(bar && bar.querySelector(".qs7-ln-input.is-dirty")); }

    var retype = {};          // key -> true: animate that box when the slide comes back

    function apply(bar) {
        var btn = bar && bar.querySelector('button[id*="qs-tf-apply"]');
        if (!btn) { return; }
        btn.click();          // the capture-phase click handler below records the retype
    }

    function toast(text) {
        var root = document.querySelector(".qs-root") || document.body;
        var el = root.querySelector(":scope > .qs7-toast");
        if (!el) {
            el = document.createElement("div");
            el.className = "qs7-toast";
            root.appendChild(el);
        }
        el.innerHTML = '<i class="bi bi-check2-circle"></i><span></span>';
        el.querySelector("span").textContent = text;
        el.classList.add("is-on");
        window.clearTimeout(el._t);
        el._t = window.setTimeout(function () { el.classList.remove("is-on"); }, 1800);
    }

    document.addEventListener("input", function (event) {
        var area = event.target;
        if (!area.classList || !area.classList.contains("qs7-ln-input")) { return; }
        area.classList.add("is-dirty");
        autoGrow(area);
        var bar = barOf(area);
        if (bar) { preview(bar); }
    }, true);

    document.addEventListener("keydown", function (event) {
        var bar = barOf(event.target);
        if (!bar) { return; }
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            apply(bar);
        } else if (event.key === "Escape") {
            dropPreview(bar);
            var close = bar.querySelector('button[id*="qs7-close"]');
            if (close) { close.click(); }
        }
    }, true);

    // Leaving the bar with unapplied words applies them, so a click elsewhere never
    // silently throws away what was typed.
    document.addEventListener("focusout", function (event) {
        var bar = barOf(event.target);
        if (!bar || !isDirty(bar)) { return; }
        var next = event.relatedTarget;
        if (next && bar.contains(next)) { return; }
        window.setTimeout(function () {
            if (document.activeElement && bar.contains(document.activeElement)) { return; }
            if (bar.isConnected && isDirty(bar)) { apply(bar); }
        }, 120);
    }, true);

    document.addEventListener("click", function (event) {
        var t = event.target;
        var applyBtn = t.closest && t.closest('button[id*="qs-tf-apply"]');
        if (applyBtn) {
            var bar = barOf(applyBtn);
            if (bar) { retype[bar.getAttribute("data-at")] = {how: "apply", at: Date.now()}; }
            return;
        }
        var closeBtn = t.closest && t.closest('button[id*="qs7-close"]');
        if (closeBtn) {
            // Closing discards what was not applied: the words drawn on the slide go too.
            var cb = barOf(closeBtn);
            if (cb) {
                cb.querySelectorAll(".qs7-ln-input.is-dirty").forEach(function (a) { a.classList.remove("is-dirty"); });
                dropPreview(cb);
            }
            return;
        }
        var reset = t.closest && t.closest('button[id*="qs-tf-reset"]');
        if (reset) {
            var b = barOf(reset);
            if (b) { retype[b.getAttribute("data-at")] = {how: "reset", at: Date.now()}; }
            return;
        }
        // Dock the panel on the side of the stage away from the box just clicked.
        var pick = t.closest && t.closest(".qs7-canvas .qs-tf-pick");
        if (pick) {
            var stage = pick.closest(".qs7-stage-wrap");
            if (stage) {
                var r = pick.getBoundingClientRect(), sr = stage.getBoundingClientRect();
                dockLeft = (r.left + r.width / 2) > (sr.left + sr.width / 2);
                dockTop = Math.max(12, r.top - sr.top - 8);   // level with the box clicked
                applyDock();
            }
        }
    }, true);

    var dockLeft = false, dockTop = 12;
    function applyDock() {
        var body = document.querySelector(".qs7-canvas .qs7-body");
        if (!body) { return; }
        body.classList.toggle("dock-left", dockLeft);
        var panel = body.querySelector(".qs7-drawer");
        if (!panel) { return; }
        // Keep the whole panel inside the stage: level with the box where it fits, pulled up
        // where the box is low on the slide.
        var room = body.clientHeight - panel.offsetHeight - 12;
        panel.style.top = Math.max(12, Math.min(dockTop, room)) + "px";
    }

    // After Dash repaints the slide or the panel: keep the dock side, size the fields,
    // and play the retype for whatever was just applied.
    function adoptCanvas() {
        applyDock();
        document.querySelectorAll(".qs7-ln-input:not([data-qs7])").forEach(function (area) {
            area.setAttribute("data-qs7", "1");
            autoGrow(area);
        });
        Object.keys(retype).forEach(function (key) {
            var pending = retype[key];
            // An Apply that changed nothing never repaints the slide; do not let it fire
            // on some later, unrelated repaint.
            if (Date.now() - pending.at > 6000) { delete retype[key]; return; }
            var box = boxFor(key);
            if (!box || box.querySelector(":scope > .qs7-live")) { return; }
            delete retype[key];
            toast(pending.how === "reset" ? "Text restored from the deck"
                                          : "Applied — written into the PowerPoint on export");
        });
    }

    var canvasQueued = false;
    new MutationObserver(function () {
        if (canvasQueued) { return; }
        canvasQueued = true;
        window.requestAnimationFrame(function () { canvasQueued = false; adoptCanvas(); });
    }).observe(document.documentElement, {childList: true, subtree: true});

    /* ── in-page links scroll the Studio pane (it scrolls itself, not the window) ── */

    document.addEventListener("click", function (event) {
        var link = event.target.closest && event.target.closest('.qs-root a[href^="#qs8-"]');
        if (!link) { return; }
        var target = document.getElementById(link.getAttribute("href").slice(1));
        if (!target) { return; }
        event.preventDefault();
        target.scrollIntoView({block: "start", behavior: reduceMotion ? "auto" : "smooth"});
    }, true);

    /* ── the build card's timer ticks every second, not once per poll ──────── */

    function clock(seconds) {
        seconds = Math.max(0, Math.floor(seconds));
        if (seconds < 60) { return seconds + "s"; }
        var s = seconds % 60;
        return Math.floor(seconds / 60) + "m " + (s < 10 ? "0" : "") + s + "s";
    }
    window.setInterval(function () {
        document.querySelectorAll(".qs6-gen-timer[data-elapsed]").forEach(function (el) {
            var server = parseInt(el.getAttribute("data-elapsed"), 10) || 0;
            if (el._server !== server) { el._server = server; el._at = Date.now(); }
            el.textContent = clock(server + (Date.now() - el._at) / 1000);
        });
    }, 1000);

    /* ── text that changes with a short cross-fade ─────────────────────────── */

    var SWAP = "#qs6-cover-carrier, #qs6-cover-period, #qs6-cover-scope, #qs6-status-text, " +
               "#qs6-summary, #qs6-month-text";
    var last = new WeakMap();

    function swap(el) {
        var text = el.textContent;
        if (last.has(el) && last.get(el) !== text && !reduceMotion) {
            el.classList.remove("qs6-swap");
            void el.offsetWidth;
            el.classList.add("qs6-swap");
        }
        last.set(el, text);
    }

    var queued = false;
    new MutationObserver(function () {
        if (queued) { return; }
        queued = true;
        window.requestAnimationFrame(function () {
            queued = false;
            document.querySelectorAll(SWAP).forEach(swap);
        });
    }).observe(document.documentElement, {childList: true, subtree: true, characterData: true});
})();
