const test = require("node:test");
const assert = require("node:assert/strict");

const { resolveDark } = require("./theme-helpers.js");

test("resolveDark follows explicit light and dark themes", function () {
  assert.equal(resolveDark("light"), false);
  assert.equal(resolveDark("dark"), true);
});
