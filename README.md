# MKWii Object Info Editor

A Windows desktop editor for the object documentation used by [MKWii Advanced Editor](https://github.com/WiiListZ/mkwii-advanced-editor).
The shared document is **[`data/objects.json`](data/objects.json)**. Contributions are reviewed as pull requests; after merging into `main`, the main editor downloads the updated documentation at its next start.

## Run

Download **[ObjectInfoEditor.exe from the latest release](https://github.com/WiiListZ/mkwii-advanced-editor-object-info/releases/latest/download/ObjectInfoEditor.exe)** and open it. Public release downloads do not require a GitHub login. Each release also includes the checksum and this guide. The [Auto pre-release](https://github.com/WiiListZ/mkwii-advanced-editor-object-info/releases/tag/auto) contains the most recent successful build of `main`.

The Windows ZIP is also available under **Artifacts** in the [build workflow](https://github.com/WiiListZ/mkwii-advanced-editor-object-info/actions/workflows/build.yml). Artifacts require GitHub sign-in and are retained for 30 days; release assets remain available until replaced or removed.

Open **`dist/ObjectInfoEditor.exe`**. The portable executable includes Python, the interface, the icon and an offline documentation snapshot; no Python installation is needed. Its working copy is saved under `%LOCALAPPDATA%\MKWii Object Info Editor\objects.json`. You can use **Open…** or **Save as…** to work elsewhere. Dropping a JSON on the executable opens that file.

For the source version, install Python **3.11 or newer** and double-click **`Start.bat`**, or run:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe objinfo_editor.py
```

The source version starts with the project's `data/objects.json`. You can also pass a JSON path as the first argument.

## Write documentation

1. Find an object by internal name, ID, label, description or notes. Filter by documentation status or validation problems.
2. Edit its description, notes, status and percentage. Use an ObjFlow internal name (`kuribo`), decimal ID (`101`) or hexadecimal ID (`0x0065`) as its key. Numeric aliases refer to the same object.
3. Enable any of settings **1–8** whose behaviour is known. Give each a label, description, choices (`0 = Off`, one per line), optional limits and signed range. Leave unverified settings undocumented.
4. Use **Preview object / JSON…** to see the description, setting guidance and JSON. Validation problems appear in red; invalid contributions cannot be proposed.
5. Save. **Undo / Redo** also restore object creation, removal, renaming and synchronization. Shortcuts: `Ctrl+S`, `Ctrl+O`, `Ctrl+F`, `Ctrl+Z`, `Ctrl+Y`.

`status` is `documented`, `partial` or `unknown`. `documented` is an integer percentage, 0–100. A documented object needs 100%; leave status/percentage empty to use the main editor's estimate. Use English for shared documentation and identify sources or game tests in the pull request.

## Know whether you are up to date

At startup, every **five minutes**, and when you click **Check now**, the program checks GitHub in the background. The banner reports:

- **Documentation is up to date with GitHub** (local edits are identified separately).
- **New documentation available on GitHub**, with the number of changed objects.
- **Cannot check GitHub / working offline**, or **GitHub is not initialized yet**. An unavailable check is never reported as up to date.

Checking does not replace your file. **Sync from GitHub** combines the latest shared documentation with your local edits. Independent changes, including different fields of the same object, are combined. When both sides edit the same field, choose your value or GitHub's value. Cancelling keeps your original file intact.

The hidden companion file `.objects.json.objinfo-base.json` records the version your changes started from. Keep it beside the JSON when moving a contribution between computers. If it is absent, the bundled baseline is used and conflicting fields require review. Saving does not erase the contribution's baseline. `data/baseline.json` is the shipped snapshot for new workspaces; maintainers can refresh it when releasing the tool. Contributors normally change only `data/objects.json`.

## Propose a pull request

Choose **Propose on GitHub…**. The program compares a snapshot of your work with the latest `main`, combines independent changes, asks about conflicts and shows the exact JSON diff. Existing contributions from other people are preserved.

- **In your browser:** copy the reviewed JSON and open GitHub's editor. Paste over the file, choose **a new branch**, commit and create a pull request. GitHub offers a fork for contributors without write access. Check the final diff before submitting; if `main` changed while the browser was open, reopen the proposal preview first. The title and evidence can be copied from the proposal form.
- **In the program:** provide a title, evidence/description and a personal access token. A classic `public_repo` token works for public repositories. A fine-grained token needs Contents and Pull requests write permission on the relevant repositories; GitHub's fork restrictions may require an external contributor to use a classic token or the browser route. The token is used in memory and never written to disk. The program creates a separate branch (and a fork for other contributors), commits the reviewed file and opens a pull request. It never writes directly to `main` or merges the PR.

If upstream changes after the preview, automatic submission stops and asks you to review again. If the commit succeeds but creating the pull request fails, the error supplies a comparison URL so you can finish using the existing branch.

## Shared documentation

The shared file is [`data/objects.json`](https://github.com/WiiListZ/mkwii-advanced-editor-object-info/blob/main/data/objects.json) on `main`. Open **Check now** to check for changes, **Sync from GitHub** to incorporate them, or **Propose on GitHub…** to contribute. This repository also includes the editor sources and CI checks.

`.gitignore` excludes the virtual environment, builds, caches and local baseline companions. The program remains usable offline.

## Editor 1.0.1

Object selection reuses the form controls instead of rebuilding the whole interface. Setting fields are created only when needed, typing updates are grouped after a short pause, and unchanged object lists are kept in place. Save, preview, object switching and submission still commit the current input immediately.

## Validate and build

```powershell
.venv\Scripts\python.exe scripts/validate.py
.venv\Scripts\python.exe -m unittest discover -v
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe scripts/build.py
```

If an older executable is running, build into another folder with `python scripts/build.py --output-dir dist/1.0.1`.

The Windows build runs validation and tests, then writes the executable, SHA-256 checksum and this guide into `dist/`. GitHub Actions validates every push and pull request. **Build Object Info Editor for Windows** automatically builds on every push to `main`, on tags beginning with `editor-v`, and when started manually with **Run workflow**. Successful builds of `main` update the **Auto** pre-release. A version tag matching `objinfo.__version__` (for example, `editor-v1.0.1`) publishes a stable release. Releases contain the executable, checksum and guide; the workflow also uploads a ZIP artifact. A new release is kept as a draft until its files are uploaded. Network contribution tests use mocks and never create real forks, commits or pull requests.

The validation rules match `parseObjectDocumentation` in the main editor: 1–1000 object entries, eight setting slots, 16-bit setting values (signed where declared), valid choices and min/max bounds, and consistent documented status. Duplicate JSON keys and invalid JSON numbers are rejected rather than silently discarded.
