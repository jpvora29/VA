/* Boardroom Studio deck navigation — prev/next, counter, filmstrip.
   No framework: event delegation + a light poll to bind the scroll listener once
   the Dash-rendered stage exists. Survives re-renders. */
(function () {
  "use strict";

  function stage() { return document.getElementById("studio-stage"); }

  function slideWidth(s) {
    var slide = s.querySelector(".studio-slide");
    return slide ? slide.getBoundingClientRect().width : s.getBoundingClientRect().width;
  }

  function current(s) {
    return Math.round(s.scrollLeft / slideWidth(s));
  }

  function goTo(i) {
    var s = stage();
    if (!s) return;
    var n = s.querySelectorAll(".studio-slide").length;
    i = Math.max(0, Math.min(n - 1, i));
    s.scrollTo({ left: i * slideWidth(s), behavior: "smooth" });
    paint(i);
  }

  function paint(i) {
    var now = document.getElementById("studio-counter-now");
    if (now) now.textContent = String(i + 1);
    var thumbs = document.querySelectorAll(".studio-thumb");
    thumbs.forEach(function (t, idx) { t.classList.toggle("active", idx === i); });
    var active = thumbs[i];
    if (active && active.scrollIntoView) active.scrollIntoView({ inline: "center", block: "nearest" });
  }

  // Click delegation: prev/next buttons (data-dir) and filmstrip thumbs (data-go).
  document.addEventListener("click", function (e) {
    var dir = e.target.closest("[data-dir]");
    if (dir) { goTo(current(stage()) + parseInt(dir.getAttribute("data-dir"), 10)); return; }
    var go = e.target.closest("[data-go]");
    if (go) { goTo(parseInt(go.getAttribute("data-go"), 10)); return; }
  });

  // Keyboard arrows when the deck is on screen.
  document.addEventListener("keydown", function (e) {
    if (!stage()) return;
    if (e.key === "ArrowRight") goTo(current(stage()) + 1);
    else if (e.key === "ArrowLeft") goTo(current(stage()) - 1);
  });

  // Bind the scroll->counter listener once the stage appears.
  var bound = false;
  var poll = setInterval(function () {
    var s = stage();
    if (!s || bound) return;
    bound = true;
    var raf;
    s.addEventListener("scroll", function () {
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(function () { paint(current(s)); });
    });
    paint(0);
    clearInterval(poll);
  }, 250);
})();
