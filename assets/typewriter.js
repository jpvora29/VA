/*
 * Placeholder guidance for the chat input (#user-input).
 *
 * This file used to TYPE example questions into the placeholder, character by
 * character, forever. Two things were wrong with that. The examples now live on
 * the starter chips, where they can be clicked and edited rather than watched;
 * and a caret moving inside the field you are about to type in competes with the
 * thing the screen is for. Motion that repeats is motion the reader has to learn
 * to ignore.
 *
 * What is left is the part that was doing real work: the placeholder says
 * something different before the first question than it does after it, because
 * "Ask anything" is the wrong prompt once there is an answer on screen to follow
 * up on.
 *
 * The input is rendered asynchronously by a Dash callback, so the DOM is watched
 * with a MutationObserver and the text is set once the element appears.
 */
(function () {
    "use strict";

    var IDLE_PLACEHOLDER = "Ask about premium, Share of Wallet, brokers or rates";
    var FOLLOWUP_PLACEHOLDER = "Ask a follow-up about this analysis…";

    function conversationStarted() {
        return !!document.querySelector(".user-message");
    }

    function apply(input) {
        if (!input) {
            return;
        }
        input.setAttribute(
            "placeholder",
            conversationStarted() ? FOLLOWUP_PLACEHOLDER : IDLE_PLACEHOLDER
        );
    }

    function scan() {
        apply(document.getElementById("user-input"));
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", scan);
    } else {
        scan();
    }

    // The composer mounts (and the first answer lands) long after this file runs.
    new MutationObserver(scan).observe(document.documentElement, {
        childList: true,
        subtree: true,
    });
})();
