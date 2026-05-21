const test = require("node:test");
const assert = require("node:assert/strict");

const { applyToggleAppearance, rollbackOptimisticToggle } = require("./toggle-helpers.js");

function mockRow() {
  const state = { opacity: false, titles: [] };
  return {
    state: state,
    classList: {
      toggle: function (name, value) {
        if (name === "opacity-70") state.opacity = value;
      },
    },
    querySelectorAll: function () {
      return state.titles.map(function (title) {
        return {
          classList: {
            toggle: function (name, value) {
              if (name === "line-through") title.struck = value;
            },
          },
        };
      });
    },
  };
}

test("applyToggleAppearance marks row and title as done", function () {
  const title = { struck: false };
  const row = mockRow();
  row.state.titles = [title];

  applyToggleAppearance(row, true);

  assert.equal(row.state.opacity, true);
  assert.equal(title.struck, true);
});

test("rollbackOptimisticToggle reverts checkbox and row styling", function () {
  const title = { struck: true };
  const row = mockRow();
  row.state.titles = [title];
  row.state.opacity = true;

  const checkbox = {
    checked: true,
    matches: function (selector) {
      return selector === "[data-optimistic-toggle]";
    },
    closest: function () {
      return row;
    },
  };

  rollbackOptimisticToggle(checkbox);

  assert.equal(checkbox.checked, false);
  assert.equal(row.state.opacity, false);
  assert.equal(title.struck, false);
});

test("rollbackOptimisticToggle ignores non-toggle inputs", function () {
  const checkbox = {
    checked: true,
    matches: function () {
      return false;
    },
    closest: function () {
      throw new Error("should not resolve row");
    },
  };

  rollbackOptimisticToggle(checkbox);

  assert.equal(checkbox.checked, true);
});
