# VS Code / Cursor setup

Source Control only works when this **folder** (`Python/ToDo`, the one that contains `.git`) is the workspace root.

## Open the repo correctly

**Preferred:** `File → Open Workspace from File…` → choose `ToDo.code-workspace` in this directory.

**Also fine:** `File → Open Folder…` → select `C:\Users\princ\Python\ToDo` (not `Python`, not your home directory).

You should see `main` (or your branch) in the status bar and changes under **Source Control**.

## If modified files still do not appear

1. Confirm the integrated terminal agrees with the UI:
   ```powershell
   git status
   ```
   If the terminal shows changes but Source Control does not, continue below.

2. **Command Palette** (`Ctrl+Shift+P`) → **Git: Open Repository…** → pick this `ToDo` folder.

3. **Command Palette** → **Developer: Reload Window**.

4. Check that Git is installed and on `PATH`:
   ```powershell
   git --version
   ```

5. Do **not** open a parent folder and expect Git to attach automatically. With `git.openRepositoryInParentFolders` set to `never` (recommended here and in many user profiles), the editor will not bind a parent workspace to this nested repo—you must open `ToDo` itself or the workspace file.

## Workspace settings in this folder

`.vscode/settings.json` enables Git refresh, limits repo scan depth to this tree, and points Python at `.venv`. Adjust `python.defaultInterpreterPath` if you use a different virtualenv location.
