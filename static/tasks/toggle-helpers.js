(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.TodoToggleHelpers = factory();
  }
})(typeof self !== "undefined" ? self : globalThis, function () {
  function applyToggleAppearance(row, done) {
    if (!row) return;
    row.classList.toggle("opacity-70", done);
    row.querySelectorAll("[data-task-title]").forEach(function (title) {
      title.classList.toggle("line-through", done);
    });
  }

  function rollbackOptimisticToggle(checkbox) {
    if (!checkbox || !checkbox.matches || !checkbox.matches("[data-optimistic-toggle]")) {
      return;
    }
    checkbox.checked = !checkbox.checked;
    applyToggleAppearance(checkbox.closest("[data-task-row]"), checkbox.checked);
  }

  return {
    applyToggleAppearance: applyToggleAppearance,
    rollbackOptimisticToggle: rollbackOptimisticToggle,
  };
});
