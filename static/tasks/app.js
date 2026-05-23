(function () {
  function getCookie(name) {
    return document.cookie
      .split("; ")
      .find((row) => row.startsWith(name + "="))
      ?.split("=")[1];
  }

  function refreshIcons() {
    if (window.lucide) {
      window.lucide.createIcons();
    }
  }

  var themeHelpers = window.TodoThemeHelpers || {};

  function initThemeToggle(root) {
    root.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      if (button.dataset.bound) return;
      button.dataset.bound = "true";
      button.addEventListener("click", () => {
        if (themeHelpers.cycleTheme) {
          themeHelpers.cycleTheme();
        }
        refreshIcons();
      });
    });
  }

  var toggleHelpers = window.TodoToggleHelpers || {};
  var applyToggleAppearance = toggleHelpers.applyToggleAppearance;
  var rollbackOptimisticToggle = toggleHelpers.rollbackOptimisticToggle;

  function initRecurrenceForms(root) {
    root.querySelectorAll("[data-recurrence-form]").forEach((form) => {
      var frequency = form.querySelector("[data-recurrence-frequency]");
      var weekdays = form.querySelector("[data-weekday-fields]");
      var monthday = form.querySelector("[data-monthday-field]");
      if (!frequency || !weekdays || !monthday) return;

      function sync() {
        weekdays.classList.toggle("hidden", frequency.value !== "weekly");
        monthday.classList.toggle("hidden", frequency.value !== "monthly");
      }

      if (!form.dataset.bound) {
        frequency.addEventListener("change", sync);
        form.dataset.bound = "true";
      }
      sync();
    });
  }

  function initSortables(root) {
    if (!window.Sortable || !window.htmx) return;
    root.querySelectorAll("[data-sortable-list]").forEach((list) => {
      if (list.dataset.sortableBound) return;
      list.dataset.sortableBound = "true";
      var draggable = list.id === "task-list" ? ".task-group" : ".subtask-row";
      new Sortable(list, {
        animation: 140,
        handle: ".drag-handle",
        draggable: draggable,
        ghostClass: "opacity-40",
        onEnd: function () {
          var ids = Array.from(list.querySelectorAll(draggable))
            .map((item) => item.dataset.taskId)
            .filter(Boolean);
          if (!list.dataset.reorderUrl || !ids.length) return;
          window.htmx.ajax("POST", list.dataset.reorderUrl, {
            target: list,
            swap: "none",
            values: { order: ids },
          });
        },
      });
    });
  }

  function focusNavRow(row) {
    if (!row) return;
    var target =
      row.querySelector("[data-nav-focus]") ||
      row.querySelector('input:not([type="hidden"]), button, a, [tabindex]:not([tabindex="-1"])');
    target?.focus({ preventScroll: true });
  }

  function initShortcutsHelp(root) {
    var dialog = document.getElementById("keyboard-shortcuts-dialog");
    if (!dialog || dialog.dataset.bound) return;
    dialog.dataset.bound = "true";

    function openShortcutsHelp() {
      if (!dialog.open) {
        dialog.showModal();
        refreshIcons();
      }
    }

    function closeShortcutsHelp() {
      if (dialog.open) {
        dialog.close();
      }
    }

    root.querySelectorAll("[data-shortcuts-help]").forEach((button) => {
      button.addEventListener("click", openShortcutsHelp);
    });
    root.querySelectorAll("[data-close-shortcuts]").forEach((button) => {
      button.addEventListener("click", closeShortcutsHelp);
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        closeShortcutsHelp();
      }
    });
  }

  function openShortcutsHelp() {
    document.getElementById("keyboard-shortcuts-dialog")?.showModal();
    refreshIcons();
  }

  function isTypingContext() {
    var tag = document.activeElement?.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
  }

  function initKeyboard() {
    if (document.body.dataset.keyboardBound) return;
    document.body.dataset.keyboardBound = "true";
    document.addEventListener("keydown", (event) => {
      var dialog = document.getElementById("keyboard-shortcuts-dialog");
      if (dialog?.open) {
        return;
      }

      var focusedIndex = parseInt(document.body.dataset.navFocusIndex || "-1", 10);
      if (event.altKey && event.key.toLowerCase() === "n") {
        event.preventDefault();
        document.querySelector("[data-new-task-input]")?.focus();
        return;
      }
      if (event.altKey && event.key === "/") {
        event.preventDefault();
        document.querySelector("[data-search-input]")?.focus();
        return;
      }
      if (event.key === "?" && !event.altKey && !event.ctrlKey && !event.metaKey) {
        if (isTypingContext()) return;
        event.preventDefault();
        openShortcutsHelp();
        return;
      }

      var editForm = event.target.closest?.("[data-edit-form]");
      if (editForm && event.key === "Escape") {
        event.preventDefault();
        editForm.querySelector("[data-cancel-edit]")?.click();
        return;
      }
      if (
        editForm &&
        event.key === "Enter" &&
        event.target.tagName !== "TEXTAREA" &&
        !event.shiftKey
      ) {
        event.preventDefault();
        editForm.requestSubmit();
        return;
      }

      if (
        ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(document.activeElement.tagName)
      ) {
        return;
      }
      if (!["j", "k"].includes(event.key.toLowerCase())) return;

      var taskList = document.getElementById("task-list");
      if (!taskList) return;
      var rows = Array.from(taskList.querySelectorAll("[data-nav-row]"));
      if (!rows.length) return;
      event.preventDefault();
      focusedIndex =
        event.key.toLowerCase() === "j"
          ? Math.min(rows.length - 1, focusedIndex + 1)
          : Math.max(0, focusedIndex - 1);
      rows.forEach((row) => row.classList.remove("ring-2", "ring-emerald-500"));
      rows[focusedIndex].classList.add("ring-2", "ring-emerald-500");
      rows[focusedIndex].scrollIntoView({ block: "nearest" });
      focusNavRow(rows[focusedIndex]);
      document.body.dataset.navFocusIndex = String(focusedIndex);
    });
  }

  function rememberFocusTarget(elt) {
    if (!elt) return;
    var row = elt.closest?.("[data-nav-row]");
    if (!row?.id) return;
    document.body.dataset.htmxFocusTarget = row.id;
    var taskList = document.getElementById("task-list");
    var rows = taskList
      ? Array.from(taskList.querySelectorAll("[data-nav-row]"))
      : [];
    var index = rows.indexOf(row);
    var next = index >= 0 ? rows[index + 1] : null;
    if (next?.id) {
      document.body.dataset.htmxFocusNextTarget = next.id;
    } else {
      delete document.body.dataset.htmxFocusNextTarget;
    }
  }

  function restoreFocusAfterSwap() {
    var targetId = document.body.dataset.htmxFocusTarget;
    if (!targetId) return;
    var nextTargetId = document.body.dataset.htmxFocusNextTarget;
    delete document.body.dataset.htmxFocusTarget;
    delete document.body.dataset.htmxFocusNextTarget;

    var row = document.getElementById(targetId);
    if (row) {
      focusNavRow(row);
      return;
    }
    if (nextTargetId) {
      row = document.getElementById(nextTargetId);
      if (row) {
        focusNavRow(row);
        return;
      }
    }
    var fallback = document.querySelector("#task-list [data-nav-row]");
    focusNavRow(fallback);
  }

  function showToast(message, isError) {
    var region = document.getElementById("toast-region");
    if (!region || !message) return;
    var toast = document.createElement("div");
    toast.setAttribute("role", isError ? "alert" : "status");
    toast.className = isError
      ? "rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-900 shadow-lg dark:border-red-900 dark:bg-red-950/40 dark:text-red-100"
      : "rounded-md border border-stone-200 bg-white px-4 py-3 text-sm font-medium text-stone-900 shadow-lg dark:border-zinc-800 dark:bg-zinc-900 dark:text-stone-100";
    toast.textContent = message;
    region.appendChild(toast);
    setTimeout(() => toast.remove(), 2800);
  }

  function setProgressVisible(visible) {
    var bar = document.getElementById("htmx-progress");
    if (!bar) return;
    bar.classList.toggle("opacity-0", !visible);
    bar.classList.toggle("opacity-100", visible);
  }

  function init(root) {
    initThemeToggle(root);
    initRecurrenceForms(root);
    initSortables(root);
    initShortcutsHelp(root);
    refreshIcons();
  }

  document.addEventListener("DOMContentLoaded", () => {
    init(document);
    initKeyboard();
  });

  document.body.addEventListener("htmx:configRequest", (event) => {
    var token = decodeURIComponent(getCookie("csrftoken") || "");
    if (token) {
      event.detail.headers["X-CSRFToken"] = token;
    }
  });

  document.body.addEventListener("htmx:beforeRequest", (event) => {
    setProgressVisible(true);
    rememberFocusTarget(event.detail.elt);
    var checkbox = event.detail.elt;
    if (!checkbox.matches?.("[data-optimistic-toggle]") || !applyToggleAppearance) return;
    var row = checkbox.closest("[data-task-row]");
    applyToggleAppearance(row, checkbox.checked);
  });

  function resetNewTaskForm(trigger) {
    if (!trigger?.closest) return;
    var newTaskForm = trigger.closest("#new-task-form");
    if (newTaskForm) {
      newTaskForm.reset();
      var details = newTaskForm.querySelector("[data-new-task-details]");
      if (details) {
        details.open = false;
      }
      newTaskForm.querySelector("[data-new-task-input]")?.focus();
      return;
    }
    var subtaskForm = trigger.closest("[id^='subtask-form-']");
    if (!subtaskForm) return;
    subtaskForm.reset();
    subtaskForm.querySelector('input[name="title"]')?.focus();
  }

  document.body.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.xhr.status === 422) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });

  document.body.addEventListener("htmx:afterRequest", (event) => {
    setProgressVisible(false);
    if (event.detail.successful) {
      resetNewTaskForm(event.detail.elt);
    }
  });

  document.body.addEventListener("htmx:responseError", (event) => {
    setProgressVisible(false);
    if (event.detail.xhr?.status === 422) {
      return;
    }
    var requestPath = event.detail.pathInfo?.requestPath || "";
    if (requestPath.includes("/reorder") && window.htmx) {
      window.htmx.ajax(
        "GET",
        window.location.pathname + window.location.search,
        {
          target: "#task-list-frame",
          swap: "outerHTML",
        }
      );
    }
    if (event.detail.xhr?.getResponseHeader("HX-Trigger")) {
      return;
    }
    var checkbox = event.detail.elt;
    if (rollbackOptimisticToggle) {
      rollbackOptimisticToggle(checkbox);
    }
    if (!checkbox?.matches?.("[data-optimistic-toggle]")) {
      showToast("Request failed. Please try again.", true);
    }
  });

  document.body.addEventListener("htmx:afterSettle", (event) => {
    init(event.target || document);
    restoreFocusAfterSwap();
    if (document.body.dataset.keyboardBound) {
      document.body.dataset.navFocusIndex = "-1";
    }
  });

  document.body.addEventListener("showToast", (event) => {
    var payload = event.detail?.value || event.detail || {};
    showToast(payload.message || payload, Boolean(payload.error));
  });
})();
