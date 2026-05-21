# Changelog

All notable changes to this academic To-Do project.

## Unreleased

### Added
- Playwright E2E smoke tests (`tasks/tests_e2e.py`)
- Node unit tests for toggle and theme helpers
- `TaskQuerySet.apply_list_filters()` for list detail filtering/sorting
- Subtask count OOB updates on subtask mutations
- HTMX global progress bar and error toasts
- J/K navigation focuses row controls; dark mode cycles light → dark → system
- ADR 0009 (dual notification channels), CONTRIBUTING.md

### Improved
- View test coverage to ~98%; overall `tasks/` coverage to ~95%+
- CI runs black, Node tests, and Playwright
- Spec §12 documents full toolchain
- E2E tests for reorder, recurrence, empty state; signal/service edge coverage
- Accessibility: `aria-live` toasts, focus restore after HTMX swaps
