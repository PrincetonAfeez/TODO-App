const test = require("node:test");
const assert = require("node:assert/strict");

const {
  applyTheme,
  cycleTheme,
  readThemeCookie,
  resolveDark,
} = require("./theme-helpers.js");

function setupDom(options) {
  options = options || {};
  var cookieStore = options.cookie || "";
  var darkClass = false;
  var toggles = [];

  global.document = {
    get cookie() {
      return cookieStore;
    },
    set cookie(value) {
      cookieStore = value;
    },
    documentElement: {
      classList: {
        toggle: function (name, value) {
          if (name === "dark") {
            darkClass = value;
          }
        },
      },
    },
    querySelectorAll: function (selector) {
      if (selector === "[data-theme-toggle]") {
        return toggles;
      }
      return [];
    },
  };

  global.window = {
    matchMedia: function () {
      return {
        matches: options.prefersDark === true,
        addEventListener: function () {},
        addListener: function () {},
      };
    },
  };

  return {
    get darkClass() {
      return darkClass;
    },
    get cookie() {
      return cookieStore;
    },
    addToggle: function (button) {
      toggles.push(button);
    },
  };
}

test("resolveDark follows explicit light and dark themes", function () {
  setupDom();
  assert.equal(resolveDark("light"), false);
  assert.equal(resolveDark("dark"), true);
});

test("resolveDark follows system preference when theme is system", function () {
  setupDom({ prefersDark: true });
  assert.equal(resolveDark("system"), true);

  setupDom({ prefersDark: false });
  assert.equal(resolveDark("system"), false);
});

test("readThemeCookie returns saved theme or system by default", function () {
  setupDom({ cookie: "theme=dark; path=/" });
  assert.equal(readThemeCookie(), "dark");

  setupDom({ cookie: "" });
  assert.equal(readThemeCookie(), "system");
});

test("applyTheme writes theme cookie and toggles dark class", function () {
  var dom = setupDom({ cookie: "theme=light; path=/" });

  applyTheme("dark");

  assert.match(dom.cookie, /theme=dark/);
  assert.equal(dom.darkClass, true);
});

test("cycleTheme rotates light, dark, and system", function () {
  setupDom({ cookie: "theme=light; path=/" });
  cycleTheme();
  assert.equal(readThemeCookie(), "dark");

  cycleTheme();
  assert.equal(readThemeCookie(), "system");

  cycleTheme();
  assert.equal(readThemeCookie(), "light");
});
