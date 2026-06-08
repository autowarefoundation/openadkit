/* White labels on dark mermaid nodes (Material re-applies dark text after render). */
(function () {
  function fixDarkMermaidLabels() {
    document.querySelectorAll(".oak-mermaid-dark, .oak-mermaid-dark .mermaid, .oak-mermaid-dark .mermaid svg").forEach(function (el) {
      el.style.setProperty("--md-mermaid-label-fg-color", "#ffffff");
      el.style.setProperty("--md-mermaid-label-bg-color", "transparent");
    });

    document.querySelectorAll(".oak-mermaid-dark .mermaid").forEach(function (diagram) {
      diagram.querySelectorAll("foreignObject, foreignObject *").forEach(function (el) {
        el.style.setProperty("color", "#ffffff", "important");
      });
      diagram.querySelectorAll(".nodeLabel, .label, .node text, text, tspan").forEach(function (el) {
        el.style.setProperty("color", "#ffffff", "important");
        el.style.setProperty("fill", "#ffffff", "important");
        if (el.tagName === "text" || el.tagName === "tspan") {
          el.setAttribute("fill", "#ffffff");
        }
      });
    });
  }

  function watchDarkMermaidDiagrams() {
    document.querySelectorAll(".oak-mermaid-dark .mermaid").forEach(function (diagram) {
      if (diagram.dataset.oakLabelFix) {
        return;
      }
      diagram.dataset.oakLabelFix = "1";
      new MutationObserver(fixDarkMermaidLabels).observe(diagram, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["style", "fill", "class"],
      });
      fixDarkMermaidLabels();
    });
  }

  function scheduleFixes() {
    watchDarkMermaidDiagrams();
    fixDarkMermaidLabels();
    [0, 50, 150, 400, 1000, 2000].forEach(function (delay) {
      setTimeout(fixDarkMermaidLabels, delay);
    });
  }

  if (typeof document$ !== "undefined") {
    document$.subscribe(scheduleFixes);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleFixes);
  } else {
    scheduleFixes();
  }
})();
