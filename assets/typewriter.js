/*
 * Animated placeholder for the chat input (#user-input).
 * Types and erases example questions until the user engages — i.e. types into
 * the field or sends a query (typed or via a suggestion chip). Once engaged it
 * stops permanently and does not resume, even after Dash clears the input.
 *
 * The input is rendered asynchronously by a Dash callback, so we watch the DOM
 * with a MutationObserver and attach once the element appears.
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
    var TYPE_MS = 55;      // per-character typing speed
    var ERASE_MS = 28;     // per-character erase speed
    var HOLD_MS = 1700;    // pause once a full question is typed
    var IDLE_PLACEHOLDER = "Ask anything";
    var FOLLOWUP_PLACEHOLDER = "Ask a follow-up question…";

    function conversationStarted() {
        return !!document.querySelector(".user-message");
    }

    function animate(input) {
        if (input.dataset.twInit === "1") {
            return;
        }
        input.dataset.twInit = "1";

        var sample = 0;
        var chars = 0;
        var deleting = false;
        var running = true;

        function stop() {
            running = false;
            input.setAttribute(
                "placeholder",
                conversationStarted() ? FOLLOWUP_PLACEHOLDER : IDLE_PLACEHOLDER
            );
        }

        // Expose stop() so the DOM observer can halt the animation the instant a
        // query is sent from a suggestion chip (no input/keydown event fires).
        input._twStop = stop;

        // Typing into the field engages and stops the animation for good.
        input.addEventListener("input", stop);

        function tick() {
            if (!running) {
                return;
            }
            // A sent query (typed or chip) renders a .user-message — stop for good.
            if (conversationStarted() || input.value) {
                stop();
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
            var cursor = deleting ? "" : "▋"; // caret while typing
            input.setAttribute("placeholder", PREFIX + text + cursor);
            setTimeout(tick, deleting ? ERASE_MS : TYPE_MS);
        }

        tick();
    }

    function findAndStart() {
        var input = document.getElementById("user-input");
        if (!input) {
            return;
        }
        animate(input);
        // If the conversation has already started (e.g. chip click), halt now.
        if (conversationStarted() && typeof input._twStop === "function") {
            input._twStop();
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
