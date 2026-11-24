/* Theme preference for the standalone legal pages (no app.js on them).
   External script only — no inline JS, so the existing CSP stays intact. */
(function () {
  "use strict";
  try {
    var raw = window.localStorage.getItem("fairbon.theme_mode");
    var mode = raw ? JSON.parse(raw) : "system";
    var root = document.documentElement;
    if (mode === "light" || mode === "dark") {
      root.setAttribute("data-theme", mode);
    }
  } catch (e) {
    /* private mode / corrupt value: follow the system preference */
  }
})();
