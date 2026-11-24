/* FairBon — reusable scan progress checklist (demo & real scans).
   Renders a list of steps with spinner -> check (or warning) states. */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};

  function prefersReducedMotion() {
    return global.matchMedia &&
      global.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function create(container, steps) {
    container.textContent = "";
    var list = document.createElement("ul");
    list.className = "scan-checklist";
    var rows = [];

    steps.forEach(function (label) {
      var li = document.createElement("li");
      li.className = "scan-step pending";
      var icon = document.createElement("span");
      icon.className = "scan-icon";
      icon.textContent = "○";
      var text = document.createElement("span");
      text.className = "scan-label";
      text.textContent = label;
      li.appendChild(icon);
      li.appendChild(text);
      list.appendChild(li);
      rows.push({ li: li, icon: icon, text: text });
    });
    var bar = document.createElement("div");
    bar.className = "scan-progress-bar";
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    bar.setAttribute("aria-valuenow", "0");
    var fill = document.createElement("span");
    bar.appendChild(fill);
    container.appendChild(list);
    container.appendChild(bar);

    function setState(index, state, label) {
      var row = rows[index];
      if (!row) { return; }
      row.li.className = "scan-step " + state;
      if (state === "running") { row.icon.textContent = ""; }
      if (state === "done") { row.icon.textContent = "✓"; }
      if (state === "warn") { row.icon.textContent = "!"; }
      if (label) { row.text.textContent = label; }
    }

    return {
      start: function () {
        if (rows.length) { setState(0, "running"); }
      },
      running: function (index, label) {
        setState(index, "running", label);
      },
      complete: function (index, label) {
        setState(index, "done", label);
        if (rows[index + 1]) { setState(index + 1, "running"); }
      },
      /** fraction 0..1, or null for the indeterminate (waiting) state. */
      bar: function (fraction) {
        if (fraction === null || fraction === undefined) {
          bar.className = "scan-progress-bar indeterminate";
          return;
        }
        var pct = Math.max(0, Math.min(100, Math.round(fraction * 100)));
        bar.className = "scan-progress-bar";
        bar.setAttribute("aria-valuenow", String(pct));
        fill.style.width = pct + "%";
      },
      finish: function () {
        bar.className = "scan-progress-bar";
        bar.setAttribute("aria-valuenow", "100");
        fill.style.width = "100%";
      },
      /** Sequential animation used by the demo (1.6 s total). */
      playDemo: function () {
        if (prefersReducedMotion()) {
          for (var i = 0; i < rows.length; i += 1) { setState(i, "done"); }
          this.finish();
          return Promise.resolve();
        }
        var delay = 400;
        var chain = Promise.resolve();
        rows.forEach(function (_, index) {
          chain = chain.then(function () {
            return new Promise(function (resolve) {
              setState(index, "running");
              global.setTimeout(function () {
                setState(index, "done");
                resolve();
              }, delay);
            });
          });
        });
        return chain.then(function () {
          bar.className = "scan-progress-bar";
          bar.setAttribute("aria-valuenow", "100");
          fill.style.width = "100%";
        });
      },
      warning: function (index, label) {
        setState(index, "warn", label);
      },
      isReduced: prefersReducedMotion
    };
  }

  NS.components = NS.components || {};
  NS.components.scanProgress = { create: create };
})(window);
