"""Preview, conflict resolution and the reviewed contribution flow."""

import copy
import json
import webbrowser

import customtkinter as ctk

from . import REPO_URL, docformat
from . import merge as merging
from .app import BG, BORDER, CARD, DANGER, FAINT, MUTED, SUCCESS, TEXT, WARNING, button, card, entry, font, label, textbox
from .github import WEB_EDIT_URL, GitHubError, propose, snapshot


def position(window, width, height):
    parent = window.master
    height = min(height, window.winfo_screenheight() - 100)
    x = max(0, parent.winfo_rootx() + (parent.winfo_width() - width) // 2)
    y = max(0, parent.winfo_rooty() + (parent.winfo_height() - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def close_child(window):
    parent = window.master
    window.destroy()
    if isinstance(parent, ctk.CTkToplevel) and parent.winfo_exists():
        parent.grab_set()


class TextDialog(ctk.CTkToplevel):
    def __init__(self, app, title, text):
        super().__init__(app)
        self.title(title)
        position(self, 900, 650)
        self.configure(fg_color=BG)
        self.transient(app)
        label(self, title, 17, TEXT, "bold").pack(anchor="w", padx=20, pady=14)
        field = textbox(self, 450)
        field.configure(font=font(13))
        field.pack(fill="both", expand=True, padx=20)
        field.insert("1.0", text)
        field.configure(state="disabled")
        button(self, "Close", lambda: close_child(self), width=100).pack(anchor="e", padx=20, pady=12)
        self.protocol("WM_DELETE_WINDOW", lambda: close_child(self))


class PreviewDialog(TextDialog):
    def __init__(self, app, key, record):
        if not isinstance(record, dict):
            super().__init__(app, f"Preview · {key}", docformat.dumps(record))
            return
        state, percent, estimated = docformat.status(record)
        lines = [record.get("label") or key, f"{docformat.STATUS_LABELS[state]} · {'~' if estimated else ''}{percent}%", "",
                 str(record.get("description", "Behaviour not documented yet."))]
        if record.get("notes"):
            lines += ["", "Notes", str(record["notes"])]
        settings = record.get("settings")
        for index in range(1, 9):
            setting = settings.get(str(index)) if isinstance(settings, dict) else None
            if not isinstance(setting, dict):
                lines += ["", f"{index}. Setting {index} — not documented"]
                continue
            lo, hi = (-32768, 32767) if setting.get("signed") else (0, 65535)
            lines += ["", f"{index}. {setting.get('label', '(label required)')}", str(setting.get("description", "")),
                      f"Range: {setting.get('min', lo)} to {setting.get('max', hi)}"]
            for name in ("values", "limits"):
                if setting.get(name):
                    lines.append(f"{name.capitalize()}: {setting[name]}")
            if isinstance(setting.get("options"), dict):
                lines += [f"  {k} = {v}" for k, v in setting["options"].items()]
                if setting.get("otherValues"):
                    lines.append("  Other value…")
        lines += ["", "JSON", docformat.dumps({"version": 1, "objects": {key: record}})]
        super().__init__(app, f"Preview · {key}", "\n".join(lines))


class ConflictDialog(ctk.CTkToplevel):
    def __init__(self, parent, document, conflicts, done):
        super().__init__(parent)
        self.title("Resolve documentation conflicts")
        position(self, 900, 720)
        self.configure(fg_color=BG)
        self.transient(parent)
        self.after(100, self.grab_set)
        label(self, "Choose the value for each conflicting field", 17, TEXT, "bold").pack(anchor="w", padx=20, pady=(16, 4))
        label(self, "Both you and another contributor edited these fields. Independent edits have already been combined.",
              wraplength=850).pack(anchor="w", padx=20, pady=(0, 10))
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=16)
        self.choices = []

        def value_text(value):
            if value is merging.MISSING:
                return "(deleted / absent)"
            return json.dumps(value, indent=2, ensure_ascii=False)

        for conflict in conflicts:
            box = card(scroll)
            box.pack(fill="x", pady=5)
            label(box, conflict.name, 13, TEXT, "bold", wraplength=790).pack(anchor="w", padx=12, pady=8)
            values = textbox(box, 150)
            values.pack(fill="x", padx=12)
            values.insert("1.0", f"Original:\n{value_text(conflict.base)}\n\nYour value:\n{value_text(conflict.local)}\n\nGitHub value:\n{value_text(conflict.remote)}")
            values.configure(state="disabled")
            choice = ctk.CTkSegmentedButton(box, values=["Choose…", "Use mine", "Use GitHub"], font=font(12))
            choice.set("Choose…")
            choice.pack(anchor="w", padx=12, pady=10)
            self.choices.append((conflict, choice))
        self.message = label(self, "", 12, WARNING)
        self.message.pack(anchor="w", padx=20)
        row = ctk.CTkFrame(self, fg_color=BG)
        row.pack(fill="x", padx=20, pady=12)
        button(row, "Cancel", lambda: close_child(self), width=100).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", lambda: close_child(self))

        def apply():
            if any(choice.get() == "Choose…" for _, choice in self.choices):
                self.message.configure(text="Choose a value for every conflict first.")
                return
            result = copy.deepcopy(document)
            for conflict, choice in self.choices:
                merging.resolve(result, conflict, choice.get() == "Use mine")
            close_child(self)
            done(result)
        button(row, "Apply choices", apply, primary=True, width=140).pack(side="right", padx=8)


class ProposeDialog(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Propose documentation on GitHub")
        position(self, 820, 850)
        self.minsize(720, 650)
        self.configure(fg_color=BG)
        self.transient(app)
        self.after(100, self.grab_set)
        self.local, self.base = copy.deepcopy(app.doc), copy.deepcopy(app.baseline)
        self.prepared = None
        self.latest = None
        self.busy = False
        self.submitted = False
        self.protocol("WM_DELETE_WINDOW", self.close)

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=12, pady=12)
        label(scroll, "Propose your documentation", 19, TEXT, "bold").pack(anchor="w", padx=8, pady=(4, 6))
        label(scroll, "Review the changes, then open a pull request. After a maintainer merges it, MKWii Advanced Editor downloads "
              "data/objects.json at its next start. Your local file stays editable.", wraplength=730).pack(anchor="w", padx=8)
        self.changes = label(scroll, "Comparing with GitHub…", 12, MUTED, wraplength=730)
        self.changes.pack(anchor="w", padx=8, pady=10)
        self.diff_button = button(scroll, "Review JSON changes…", self.show_diff, width=200, state="disabled")
        self.diff_button.pack(anchor="w", padx=8, pady=(0, 10))
        form = card(scroll)
        form.pack(fill="x", padx=8, pady=6)
        label(form, "Pull request title", 12).pack(anchor="w", padx=14, pady=(12, 4))
        self.title_entry = entry(form)
        self.title_entry.pack(fill="x", padx=14)
        label(form, "What changed and how you verified it (game test, source, link…)", 12).pack(anchor="w", padx=14, pady=(8, 4))
        self.body = textbox(form, 95)
        self.body.pack(fill="x", padx=14, pady=(0, 12))

        browser = card(scroll)
        browser.pack(fill="x", padx=8, pady=6)
        label(browser, "In your browser", 14, TEXT, "bold").pack(anchor="w", padx=14, pady=(12, 2))
        label(browser, "Copy the reviewed JSON, paste over data/objects.json in GitHub's editor, then commit to a NEW branch "
              "and create a pull request. Contributors without write access are offered a fork. Review the diff before submitting.",
              wraplength=690).pack(anchor="w", padx=14)
        self.browser_button = button(browser, "Copy JSON and open GitHub", self.browser, width=250, state="disabled")
        self.browser_button.pack(anchor="w", padx=14, pady=12)

        automatic = card(scroll)
        automatic.pack(fill="x", padx=8, pady=6)
        label(automatic, "Create the pull request here", 14, TEXT, "bold").pack(anchor="w", padx=14, pady=(12, 2))
        label(automatic, "Use a classic token with public_repo, or a fine-grained token with Contents and Pull requests write access "
              "to the required repositories. External contributors may need a classic token to create their fork. The token is never saved.",
              wraplength=690).pack(anchor="w", padx=14)
        self.token = entry(automatic, show="•", placeholder_text="GitHub personal access token")
        self.token.pack(fill="x", padx=14, pady=8)
        self.go = button(automatic, "Create pull request", self.automatic, primary=True, width=210, state="disabled")
        self.go.pack(anchor="w", padx=14, pady=(4, 12))
        self.progress = label(scroll, "", 12, MUTED, wraplength=730)
        self.progress.pack(anchor="w", padx=8, pady=6)
        button(self, "Close", self.close, width=100).pack(anchor="e", padx=20, pady=(0, 12))
        app.background(snapshot, self.compared, self.failed)

    def alive(self):
        return bool(self.winfo_exists())

    def close(self):
        if self.busy:
            self.progress.configure(text="Wait for the GitHub request to finish before closing.", text_color=WARNING)
        else:
            self.token.delete(0, "end")
            self.destroy()

    def failed(self, message):
        if self.alive():
            self.busy = False
            self.changes.configure(text=message, text_color=DANGER)
            self.progress.configure(text="Your work remains local. Close this window and try again after the repository is ready or the connection is restored.", text_color=WARNING)

    def compared(self, latest):
        if not self.alive():
            return
        self.latest = latest
        document, conflicts = merging.merge(self.base, self.local, latest.document)
        if conflicts:
            self.changes.configure(text=f"{len(conflicts)} conflicting fields need a choice before this proposal can be prepared.", text_color=WARNING)
            ConflictDialog(self, document, conflicts, self.ready)
        else:
            self.ready(document)

    def ready(self, document):
        if not self.alive():
            return
        try:
            docformat.parse(document)
        except ValueError as error:
            self.failed(f"The combined document needs a correction in the editor: {error}")
            return
        self.prepared = copy.deepcopy(document)
        changes = merging.changes(self.latest.document, document)
        names = [key for keys in changes.values() for key in keys]
        if not names:
            self.changes.configure(text="No changes to propose: GitHub already contains this documentation.", text_color=WARNING)
            return
        self.changes.configure(text=" · ".join(f"{len(keys)} {kind}" for kind, keys in changes.items()) + "\n" + ", ".join(names[:12]), text_color=TEXT)
        if not self.title_entry.get().strip():
            self.title_entry.insert(0, f"Object documentation: {', '.join(names[:3])}" + ("…" if len(names) > 3 else ""))
        for control in (self.diff_button, self.browser_button, self.go):
            control.configure(state="normal")

    def show_diff(self):
        if self.prepared is not None:
            dialog = TextDialog(self, "Changes proposed to data/objects.json", merging.diff(self.latest.document, self.prepared))
            dialog.after(100, dialog.grab_set)

    def browser(self):
        if self.prepared is None or self.busy:
            return
        self.clipboard_clear()
        self.clipboard_append(docformat.dumps(self.prepared))
        webbrowser.open(WEB_EDIT_URL)
        self.progress.configure(text="The reviewed JSON is copied. Paste it into GitHub; choose a new branch and review the diff before creating the pull request. "
                                "If main changes meanwhile, reopen this preview first.", text_color=SUCCESS)

    def automatic(self):
        if self.prepared is None or self.busy or self.submitted:
            return
        token, title, body = self.token.get().strip(), self.title_entry.get().strip(), self.body.get("1.0", "end").strip()
        if not token or not title or not body:
            self.progress.configure(text="Enter a token, a title, and a description with your verification or sources first.", text_color=WARNING)
            return
        self.busy = True
        self.go.configure(state="disabled")
        self.browser_button.configure(state="disabled")
        self.token.delete(0, "end")
        text, expected = docformat.dumps(self.prepared), self.latest.commit

        def say(message):
            self.app.on_ui(lambda: self.progress.configure(text=message, text_color=MUTED) if self.alive() else None)

        def done(url):
            self.busy = False
            self.submitted = True
            if self.alive():
                self.progress.configure(text=f"Pull request created: {url}", text_color=SUCCESS)
                webbrowser.open(url)

        def failed(message):
            self.busy = False
            if self.alive():
                self.progress.configure(text=message, text_color=DANGER)
                # Reopen the preview after any failure; a branch may already have been written.
                self.changes.configure(text="Close and reopen this preview before retrying. If a branch was saved, use the comparison link above.", text_color=WARNING)
        self.app.background(lambda: propose(token, text, title, body + "\n\n_Proposed with Object Info Editor._", say,
                                           expected_commit=expected), done, failed)
