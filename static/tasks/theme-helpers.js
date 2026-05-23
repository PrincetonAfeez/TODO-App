(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.TodoThemeHelpers = factory();
  }
})(typeof self !== "undefined" ? self : globalThis, function () {
  var THEME_COOKIE = "theme=";
  var CYCLE = { light: "dark", dark: "system", system: "light" };

  function readThemeCookie() {
    var saved = document.cookie.match(/(?:^|; )theme=([^;]+)/);
    return saved ? decodeURIComponent(saved[1]) : "system";
  }

  function prefersDark() {
    if (typeof window === "undefined" || !window.matchMedia) {
      return false;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function resolveDark(theme) {
    return theme === "dark" || (theme === "system" && prefersDark());
  }

  function applyTheme(theme) {
    document.documentElement.classList.toggle("dark", resolveDark(theme));
    document.cookie = THEME_COOKIE + theme + "; path=/; max-age=31536000";
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      var label =
        theme === "dark" ? "Dark mode" : theme === "light" ? "Light mode" : "System theme";
      button.title = label + " (click to change)";
    });
  }

  function cycleTheme() {
    var current = readThemeCookie();
    applyTheme(CYCLE[current] || "dark");
  }

  function initThemeFromCookie() {
    applyTheme(readThemeCookie());
    if (typeof window === "undefined" || !window.matchMedia) {
      return;
    }
    var media = window.matchMedia("(prefers-color-scheme: dark)");
    var onSystemThemeChange = function () {
      if (readThemeCookie() === "system") {
        applyTheme("system");
      }
    };
    if (media.addEventListener) {
      media.addEventListener("change", onSystemThemeChange);
    } else if (media.addListener) {
      media.addListener(onSystemThemeChange);
    }
  }

  return {
    applyTheme: applyTheme,
    cycleTheme: cycleTheme,
    initThemeFromCookie: initThemeFromCookie,
    readThemeCookie: readThemeCookie,
    resolveDark: resolveDark,
  };
});
