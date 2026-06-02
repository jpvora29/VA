/*
 * Animated placeholder for the chat input (#user-input).
 * Types and erases example questions until the user focuses or types.
 * The input is rendered asynchronously by a Dash callback, so we watch the
 * DOM with a MutationObserver and attach once the element appears.
 *
 * Keep SAMPLES aligned with STARTER_SUGGESTIONS in ui/components/chatbot.py.
 */
(function () {
    "use strict";

    var SAMPLES = [
        "What is Zurich's Share of Wallet in Canada for Property?",
        "Show premium growth for Chubb across all product lines",
        "How does AXA's broker score compare to peers this year?",
        "What is the market composite rate change for Asia this quarter?",
    ];

    var PREFIX = "Try: ";
    var TYPE_MS = 55;     // per-character typing speed
    var ERASE_MS = 28;    // per-character erase speed
    var HOLD_MS = 1700;   // pause once a full question is typed
    var IDLE_PLACEHOLDER = "Ask anything";

    function animate(input) {
        if (input.dataset.twInit === "1") {
            return;
        }
        input.dataset.twInit = "1";

        var sample = 0;
        var chars = 0;
        var deleting = false;

        function tick() {
            // Yield entirely to the user while the field is focused or has text.
            if (document.activeElement === input || input.value) {
                input.setAttribute("placeholder", IDLE_PLACEHOLDER);
                setTimeout(tick, 500);
                return;
            }

            var full = SAMPLES[sample];

            if (!deleting) {
                chars += 1;
                if (chars > full.length) {
                    deleting = true;
                    input.setAttribute("placeholder", PREFIX + full);
                    setTimeout(tick, HOLD_MS);
                    return;
                }
            } else {
                chars -= 1;
                if (chars <= 0) {
                    chars = 0;
                    deleting = false;
                    sample = (sample + 1) % SAMPLES.length;
                }
            }

            var text = full.slice(0, chars);
            var cursor = deleting ? "" : "▋"; // ▋ blinking-style caret while typing
            input.setAttribute("placeholder", PREFIX + text + cursor);
            setTimeout(tick, deleting ? ERASE_MS : TYPE_MS);
        }

        tick();
    }

    function findAndStart() {
        var input = document.getElementById("user-input");
        if (input) {
            animate(input);
        }
    }

    var observer = new MutationObserver(findAndStart);
    observer.observe(document.body, { childList: true, subtree: true });

    if (document.readyState !== "loading") {
        findAndStart();
    } else {
        document.addEventListener("DOMContentLoaded", findAndStart);
    }
})();
