# Accessibility

This app targets WCAG 2.1 Level AA for the main user flows. Automated checks
use [axe-core](https://github.com/dequelabs/axe-core) via Playwright; manual
checks cover keyboard and screen-reader behavior described below.

## Automated scans (CI)

Three pages are scanned on every E2E run (`tasks/tests_a11y_e2e.py`):

| Page | URL | What it exercises |
| --- | --- | --- |
| List detail | `/` | New task form, filters, sidebar, rename |
| Lists overview | `/lists/` | Sidebar + list cards |
| Events | `/events/` | Audit filters + table |

Run locally:

```bash
python -m playwright install chromium
python -m pytest tasks/tests_a11y_e2e.py -m e2e -v
```

Failures print an axe report with rule id, impact, and affected nodes.

## Patterns in templates

- **`lang="en"`** on `<html>` (`base.html`).
- **Landmarks** — header nav (`aria-label="Site"`), sidebar list nav
  (`aria-label="Task lists"`), pagination nav on events.
- **Form controls** — filter selects, rename field, and events filters use
  `aria-label` where a visible `<label>` would clutter compact toolbars.
- **Live regions** — flash messages use `role="alert"`; HTMX toasts use
  `role="status"` + `aria-live="polite"` (`#toast-region`).
- **Progress** — HTMX indicator is `aria-hidden="true"` (decorative).
- **Color contrast** — the main **Add task** button uses `bg-emerald-700` on white
  text (≥4.5:1). Other compact emerald actions (sidebar **+**, recurrence save)
  still use `emerald-600`; axe scans pass on the three CI pages in light mode.

## Keyboard & focus

- **Shortcuts dialog** — `?` opens a modal with focus trap (`app.js`).
- **Task toggle** — checkboxes are real `<input type="checkbox">` elements
  with optimistic UI helpers; they remain keyboard operable.
- **Sortable reorder** — drag-only; reorder is disabled when filters/search
  are active (see `edge-cases.md`). Keyboard reorder is not implemented.

## Known limitations

| Area | Limitation |
| --- | --- |
| Drag reorder | No keyboard alternative (SortableJS drag handle only). |
| Icon-only buttons | Sidebar “All lists” and create-list `+` rely on `title` / context; not ideal for SR-only users. |
| Tailwind CDN | Runtime CSS; contrast depends on utility classes, not a design-token pipeline. |
| Dark mode | Tested manually; axe scans run in light mode only. |

## Manual smoke checklist

1. Tab through new-task form → Add → task appears.
2. Tab through filter bar; status control disables on Today/Upcoming/Overdue.
3. Open shortcuts (`?`), Esc closes.
4. Toggle dark mode; confirm readable text on list rows and events table.

## Related tests

- E2E flows: `tasks/tests_e2e.py`
- axe scans: `tasks/tests_a11y_e2e.py`
- Edge-case catalog: [`edge-cases.md`](edge-cases.md)
