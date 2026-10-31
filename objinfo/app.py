"""Object Info Editor: a window to edit data/objects.json and propose the changes on GitHub.

The look follows MKWii Advanced Editor (dark, plain cards, white main buttons). Every change is
checked at once with the same rules as the editor; objects with a problem are marked in the list.
"""

from __future__ import annotations

import copy
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import DATA_PATH, REPO_URL, __version__
from . import docformat
from .github import snapshot
from . import merge as merging
from .storage import read_baseline, save_document

# ---- Look ---------------------------------------------------------------------------------------

BG = "#0e0e10"
CARD = "#161619"
FIELD = "#1d1d21"
BORDER = "#2a2a2f"
TEXT = "#f4f4f5"
MUTED = "#a1a1aa"
FAINT = "#71717a"
PRIMARY = "#fafafa"
PRIMARY_TEXT = "#18181b"
HOVER = "#27272a"
DANGER = "#f87171"
WARNING = "#fbbf24"
SUCCESS = "#4ade80"
FONT = "Segoe UI"


def resource(*parts: str) -> Path:
    """A file shipped with the program (inside the exe, or beside the sources)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def button(master, text: str, command, primary: bool = False, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, height=32, corner_radius=6, font=font(13, "bold" if primary else "normal"),
                         fg_color=PRIMARY if primary else "transparent", text_color=PRIMARY_TEXT if primary else TEXT,
                         hover_color="#d4d4d8" if primary else HOVER, border_width=0 if primary else 1, border_color=BORDER, **kw)


def entry(master, **kw) -> ctk.CTkEntry:
    return ctk.CTkEntry(master, height=32, corner_radius=6, fg_color=FIELD, border_color=BORDER, border_width=1, text_color=TEXT, font=font(13), **kw)


def textbox(master, height: int) -> ctk.CTkTextbox:
    return ctk.CTkTextbox(master, height=height, corner_radius=6, fg_color=FIELD, border_color=BORDER, border_width=1, text_color=TEXT,
                          font=font(13), wrap="word")


def label(master, text: str, size: int = 12, color: str = MUTED, weight: str = "normal", **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text, font=font(size, weight), text_color=color, anchor="w", justify="left", **kw)


def card(master) -> ctk.CTkFrame:
    return ctk.CTkFrame(master, fg_color=CARD, corner_radius=8, border_width=1, border_color=BORDER)


# ---- Options as text: one "value = label" per line ----------------------------------------------

def options_to_text(options: dict | None) -> str:
    if options is not None and not isinstance(options, dict):
        return json.dumps(options, ensure_ascii=False)
    return "\n".join(f"{k} = {v}" for k, v in (options or {}).items())


def text_to_options(text: str) -> dict | None:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^\s*(-?\d+)\s*[=:]\s*(.*?)\s*$", line)
        if m:
            key = str(int(m.group(1)))
            if key in out:
                out[f"Duplicate value {key}"] = ""
            else:
                out[key] = m.group(2)
        else:
            out[line.strip()] = ""  # reported by the check: the value must be a whole number
    return out or None


def number_or_text(text: str):
    text = text.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text  # kept so the check can say what is wrong


# ---- The window ----------------------------------------------------------------------------------

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(f"Object Info Editor {__version__}")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(fg_color=BG)
        try:
            self.iconbitmap(str(resource("assets", "icon.ico")))
        except tk.TclError:
            pass

        self.path: Path | None = None
        self.doc: dict = {"version": 1, "objects": {}}
        self.saved_text = docformat.dumps(self.doc)
        self.selected: str | None = None
        self.keys: list[str] = []  # keys shown in the list, in order
        self.errors: dict[str, str] = {}
        self.form_loading = False
        self.baseline = docformat.loads(resource("data", "baseline.json").read_text(encoding="utf-8"))
        self.shipped_baseline = copy.deepcopy(self.baseline)
        self.jobs = queue.Queue()
        self.network_busy = False
        self.checking_remote = False
        self.latest_snapshot = None
        self.remote_error = ""
        self.history = []
        self.history_index = -1
        self.history_job = None
        self.restoring_history = False
        self.form_commit_job = None
        self.form_built = False
        self.list_rows = None

        self.build()
        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<Control-f>", lambda e: self.search.focus_set())
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self.load_start)
        self.after(50, self.pump_jobs)
        self.after(800, self.check_remote)
        self.after(300000, self.periodic_check)

    def pump_jobs(self):
        try:
            while True:
                self.jobs.get_nowait()()
        except queue.Empty:
            pass
        self.after(50, self.pump_jobs)

    def on_ui(self, callback):
        self.jobs.put(callback)

    def background(self, work, done, failed):
        def run():
            try:
                result = work()
            except Exception as error:
                message = str(error)
                self.on_ui(lambda: failed(message))
            else:
                self.on_ui(lambda: done(result))
        threading.Thread(target=run, daemon=True).start()

    def periodic_check(self):
        self.check_remote()
        self.after(300000, self.periodic_check)

    def check_remote(self):
        if self.checking_remote:
            return
        self.checking_remote = True
        self.remote_label.configure(text="Checking the latest documentation on GitHub…", text_color=MUTED)
        self.check_button.configure(state="disabled")

        def done(latest):
            self.checking_remote = False
            self.latest_snapshot = latest
            self.remote_error = ""
            self.check_button.configure(state="normal")
            self.refresh_remote()

        def failed(message):
            self.checking_remote = False
            self.latest_snapshot = None
            self.remote_error = message
            self.check_button.configure(state="normal")
            self.refresh_remote()
            self.set_status(message, WARNING)
        self.background(snapshot, done, failed)

    def refresh_remote(self):
        if self.checking_remote:
            return
        if self.latest_snapshot is None:
            missing = "empty" in self.remote_error or "main branch" in self.remote_error or "missing on GitHub" in self.remote_error
            text = "GitHub is not initialized yet · local documentation is available" if missing else "Cannot check GitHub · working offline"
            self.remote_label.configure(text=text, text_color=WARNING)
            return
        latest = self.latest_snapshot.document
        # Local contributions are not evidence of being behind: compare the remote with
        # the baseline of the contribution, as well as with the current document.
        if latest == self.baseline or latest == self.doc:
            extra = " · local edits to propose" if latest != self.doc else ""
            self.remote_label.configure(text="Documentation is up to date with GitHub" + extra, text_color=SUCCESS)
        else:
            counts = merging.changes(self.baseline, latest)
            total = sum(len(keys) for keys in counts.values())
            self.remote_label.configure(text=f"New documentation available on GitHub · {total} objects changed · use Sync from GitHub", text_color=WARNING)

    def capture_history(self):
        if self.history_job:
            self.after_cancel(self.history_job)
        self.history_job = None
        if self.restoring_history:
            return
        if self.history_index >= 0 and self.history[self.history_index][0] == self.doc and self.history[self.history_index][2] == self.baseline:
            return
        del self.history[self.history_index + 1:]
        self.history.append((copy.deepcopy(self.doc), self.selected, copy.deepcopy(self.baseline)))
        if len(self.history) > 60:
            self.history.pop(0)
        self.history_index = len(self.history) - 1

    def schedule_history(self):
        if self.restoring_history:
            return
        if self.history_job:
            self.after_cancel(self.history_job)
        self.history_job = self.after(450, self.capture_history)

    def queue_form_commit(self, event=None):
        if self.form_loading:
            return
        if self.form_commit_job:
            self.after_cancel(self.form_commit_job)
        self.form_commit_job = self.after(120, self.commit_form)

    def undo(self):
        self.commit_form()
        self.capture_history()
        if self.history_index > 0:
            self.restore_history(self.history_index - 1)
        return "break"

    def redo(self):
        self.commit_form()
        self.capture_history()
        if self.history_index + 1 < len(self.history):
            self.restore_history(self.history_index + 1)
        return "break"

    def restore_history(self, index):
        if self.history_job:
            self.after_cancel(self.history_job)
            self.history_job = None
        self.restoring_history = True
        self.history_index = index
        self.doc, self.selected, self.baseline = copy.deepcopy(self.history[index])
        self.refresh_all()
        self.restoring_history = False

    # -- layout --

    def build(self):
        top = ctk.CTkFrame(self, fg_color=BG)
        top.pack(fill="x", padx=18, pady=(14, 8))
        try:
            from PIL import Image
            logo = ctk.CTkImage(Image.open(resource("assets", "icon.png")), size=(40, 40))
            ctk.CTkLabel(top, image=logo, text="").pack(side="left", padx=(0, 10))
        except Exception:
            pass
        heading = ctk.CTkFrame(top, fg_color=BG)
        heading.pack(side="left", fill="x", expand=True)
        label(heading, "Object Info Editor", 17, TEXT, "bold").pack(anchor="w")
        self.file_label = label(heading, "", 12, wraplength=1050)
        self.file_label.pack(anchor="w")
        top = ctk.CTkFrame(self, fg_color=BG)
        top.pack(fill="x", padx=18, pady=(0, 8))
        button(top, "Undo", self.undo, width=65).pack(side="left", padx=(0, 6))
        button(top, "Redo", self.redo, width=65).pack(side="left")
        button(top, "Propose on GitHub…", self.open_propose, primary=True, width=170).pack(side="right", padx=(6, 0))
        button(top, "Save as…", self.save_as, width=90).pack(side="right", padx=(6, 0))
        button(top, "Save", self.save, width=70).pack(side="right", padx=(6, 0))
        self.sync_button = button(top, "Sync from GitHub", self.download, width=140)
        self.sync_button.pack(side="right", padx=(6, 0))
        button(top, "Open…", self.open_file, width=80).pack(side="right", padx=(6, 0))

        remote = card(self)
        remote.pack(fill="x", padx=18, pady=(0, 10))
        self.remote_label = label(remote, "Checking the latest documentation on GitHub…", 12, MUTED, wraplength=900)
        self.remote_label.pack(side="left", fill="x", expand=True, padx=12, pady=8)
        self.check_button = button(remote, "Check now", self.check_remote, width=100)
        self.check_button.pack(side="right", padx=10, pady=6)

        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # Left: the objects.
        left = card(body)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        left.configure(width=345)
        left.grid_propagate(False)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        self.search = entry(left, placeholder_text="Find an object (name, ID, text)…")
        self.search.bind("<KeyRelease>", lambda _: self.refresh_list())
        self.search.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        self.filter = ctk.CTkSegmentedButton(left, values=["All", "Documented", "Partial", "Unknown", "Problems"], command=lambda _: self.refresh_list(),
                                             font=font(11), height=28, fg_color=FIELD, selected_color=HOVER, selected_hover_color=HOVER,
                                             unselected_color=FIELD, unselected_hover_color=HOVER, text_color=TEXT)
        self.filter.set("All")
        self.filter.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        frame = tk.Frame(left, bg=CARD, highlightthickness=0)
        frame.grid(row=2, column=0, sticky="nsew", padx=10)
        self.listbox = tk.Listbox(frame, bg=CARD, fg=TEXT, selectbackground=HOVER, selectforeground=TEXT, activestyle="none",
                                  highlightthickness=0, borderwidth=0, font=(FONT, 11), exportselection=False)
        scroll = ctk.CTkScrollbar(frame, command=self.listbox.yview, fg_color=CARD, button_color=BORDER, button_hover_color=FAINT)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.on_select())
        self.count_label = label(left, "", 11, FAINT, wraplength=310)
        self.count_label.grid(row=3, column=0, sticky="w", padx=12, pady=(4, 0))
        actions = ctk.CTkFrame(left, fg_color=CARD)
        actions.grid(row=4, column=0, sticky="ew", padx=10, pady=(4, 10))
        button(actions, "+ New object", self.new_object, width=110).pack(side="left")
        button(actions, "Duplicate", self.duplicate_object, width=90).pack(side="left", padx=6)
        button(actions, "Delete", self.delete_object, width=70).pack(side="left")
        button(left, "Preview object / JSON…", self.preview, width=200).grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 10))

        # Right: the selected object.
        self.form = ctk.CTkScrollableFrame(body, fg_color=BG, scrollbar_button_color=BORDER, scrollbar_button_hover_color=FAINT)
        self.form.grid(row=0, column=1, sticky="nsew")
        self.form.grid_columnconfigure(0, weight=1)

        # Bottom: the check of the whole file.
        self.status = label(self, "", 12, MUTED)
        self.status.pack(fill="x", padx=20, pady=(0, 10))

    # -- file --

    def load_start(self):
        """data/objects.json beside the program (a clone of the repository), or the latest from GitHub."""
        if len(sys.argv) > 1:
            self.load_path(Path(sys.argv[1]))
            return
        if getattr(sys, "frozen", False):
            folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MKWii Object Info Editor"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "objects.json"
            if not path.exists():
                save_document(path, self.baseline, self.baseline)
            self.load_path(path)
            return
        here = Path(__file__).resolve()
        for folder in [Path.cwd(), *here.parents]:
            candidate = folder / DATA_PATH
            if candidate.is_file():
                self.load_path(candidate)
                return
        self.load_text(docformat.dumps(self.baseline), None, "Bundled documentation (offline)")

    def load_text(self, text: str, path: Path | None, origin: str):
        try:
            doc = docformat.loads(text)
        except ValueError as error:
            messagebox.showerror("Not valid JSON", f"{origin}: {error}")
            return
        if not isinstance(doc, dict) or not isinstance(doc.get("objects"), dict):
            messagebox.showerror("Not an object documentation", f'{origin} is not {{ "version": 1, "objects": {{ ... }} }}.')
            return
        self.doc, self.path, self.saved_text = doc, path, docformat.dumps(doc)
        self.baseline = read_baseline(path, self.shipped_baseline) if path else copy.deepcopy(doc)
        self.selected = next(iter(doc["objects"]), None)
        self.origin = origin
        if self.history_job:
            self.after_cancel(self.history_job)
            self.history_job = None
        self.history = []
        self.history_index = -1
        self.capture_history()
        self.refresh_all()
        return True

    def load_path(self, path: Path):
        try:
            return self.load_text(path.read_text(encoding="utf-8-sig"), path, str(path))
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Could not open the file", str(error))

    def confirm_discard(self) -> bool:
        self.commit_form()
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Unsaved changes", "Save the changes first?")
        if answer is None:
            return False
        return self.save() if answer else True

    def open_file(self):
        if not self.confirm_discard():
            return
        name = filedialog.askopenfilename(title="Open an object documentation", filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if name:
            self.load_path(Path(name))

    def download(self, ask: bool = True):
        if self.network_busy:
            return
        self.commit_form()
        self.network_busy = True
        self.sync_button.configure(state="disabled")
        self.set_status("Reading data/objects.json from GitHub…", MUTED)
        # Capture the origin; opening another file while the request runs cancels applying it.
        document = self.doc

        def finish():
            self.network_busy = False
            self.sync_button.configure(state="normal")

        def done(latest):
            finish()
            self.latest_snapshot = latest
            self.remote_error = ""
            if self.doc is not document:
                self.set_status("Sync cancelled because another document was opened. Sync again for this document.", WARNING)
                return
            self.commit_form()
            merged, conflicts = merging.merge(self.baseline, self.doc, latest.document)

            def apply(result):
                self.capture_history()
                self.doc = result
                self.baseline = copy.deepcopy(latest.document)
                if self.selected not in self.objects:
                    self.selected = next(iter(self.objects), None)
                self.refresh_all()
                self.capture_history()
                self.set_status("Synced from GitHub. Your edits were kept. Save to keep this version locally.", SUCCESS)

            if conflicts:
                ConflictDialog(self, merged, conflicts, apply)
            else:
                apply(merged)

        def failed(message):
            finish()
            self.set_status(message, DANGER)
            if ask:
                messagebox.showerror("Could not sync", message, parent=self)
        self.background(snapshot, done, failed)

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self.write(self.path)

    def save_as(self) -> bool:
        name = filedialog.asksaveasfilename(title="Save the object documentation", defaultextension=".json", initialfile="objects.json",
                                            filetypes=[("JSON", "*.json")])
        return bool(name) and self.write(Path(name))

    def write(self, path: Path) -> bool:
        self.commit_form()
        if not self.rename():
            return False
        problem = self.check()
        if problem and not messagebox.askyesno("The file has a problem", f"{problem}\n\nThe editor will refuse this file until it is fixed. Save anyway?"):
            return False
        try:
            text = docformat.dumps(self.doc)
            save_document(path, self.doc, self.baseline)
        except OSError as error:
            messagebox.showerror("Could not save", str(error))
            return False
        self.path, self.saved_text = path, text
        self.refresh_title()
        self.set_status(f"Saved {path}.", SUCCESS)
        return True

    @property
    def dirty(self) -> bool:
        pending_key = False
        try:
            pending_key = self.selected is not None and hasattr(self, "key_entry") and self.key_entry.get().strip() != self.selected
        except tk.TclError:
            pass
        return bool(self.form_commit_job) or docformat.dumps(self.doc) != self.saved_text or pending_key

    def on_close(self):
        self.commit_form()
        if self.confirm_discard():
            self.destroy()

    # -- list --

    @property
    def objects(self) -> dict:
        return self.doc["objects"]

    def check(self) -> str | None:
        """Checks every entry (marks the ones with a problem) and the whole file; returns the first problem."""
        self.errors = {}
        for key, value in self.objects.items():
            try:
                docformat.parse_entry(key, value)
            except docformat.DocumentationError as error:
                self.errors[key] = str(error)
        if isinstance(self.doc.get("version"), bool) or self.doc.get("version") != 1:
            return 'Expected { "version": 1, "objects": { ... } }'
        if not 1 <= len(self.objects) <= 1000:
            return "Provide 1 to 1000 object entries"
        return next(iter(self.errors.values()), None)

    def refresh_all(self):
        self.refresh_list()
        self.build_form()
        self.refresh_title()
        self.refresh_remote()

    def refresh_title(self):
        where = str(self.path) if self.path else getattr(self, "origin", "not saved yet")
        self.file_label.configure(text=f"{where}{'  ·  unsaved changes' if self.dirty else ''}")

    def refresh_list(self):
        problem = self.check()
        query = self.search.get().strip().lower()
        wanted = self.filter.get()
        self.keys = []
        rows = []
        counts = {"documented": 0, "partial": 0, "unknown": 0}
        for key, value in self.objects.items():
            entry_ = value if isinstance(value, dict) else {}
            state, percent, estimated = docformat.status(entry_)
            counts[state] = counts.get(state, 0) + 1
            text = " ".join(str(entry_.get(f, "")) for f in ("label", "description", "notes"))
            if query and query not in key.lower() and query not in text.lower():
                continue
            if wanted == "Documented" and state != "documented" or wanted == "Partial" and state != "partial" \
                    or wanted == "Unknown" and state != "unknown" or wanted == "Problems" and key not in self.errors:
                continue
            mark = "⚠ " if key in self.errors else ""
            name = entry_.get("label") if isinstance(entry_.get("label"), str) else ""
            rows.append(f"{mark}{name + '  ·  ' if name else ''}{key}    {'~' if estimated else ''}{percent}%")
            self.keys.append(key)
        if rows != self.list_rows:
            self.listbox.delete(0, "end")
            if rows:
                self.listbox.insert("end", *rows)
            for i, key in enumerate(self.keys):
                if key in self.errors:
                    self.listbox.itemconfig(i, fg=DANGER)
            self.list_rows = rows
        if self.selected in self.keys:
            i = self.keys.index(self.selected)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(i)
            self.listbox.see(i)
        self.count_label.configure(text=f"{len(self.keys)} of {len(self.objects)} objects · {counts['documented']} documented, "
                                        f"{counts['partial']} partial, {counts['unknown']} unknown")
        if problem:
            self.set_status(f"Problem: {problem}", DANGER)
        else:
            self.set_status(f"Valid: {len(self.objects)} objects. The editor accepts this file.", MUTED)
        self.refresh_title()
        self.refresh_remote()

    def on_select(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        key = self.keys[sel[0]]
        if key == self.selected:
            return
        self.commit_form()
        self.selected = key
        self.build_form()
        if key in self.keys:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(self.keys.index(key))

    def unique_key(self, base: str) -> str:
        key, n = base, 2
        while key in self.objects:
            key, n = f"{base}_{n}", n + 1
        return key

    def existing_key(self, key: str) -> str | None:
        normalized = docformat.normalize_key(key)
        return next((k for k in self.objects if docformat.normalize_key(k) == normalized), None)

    def insert_after(self, key: str, value: dict, after: str | None):
        items = list(self.objects.items())
        index = next((i + 1 for i, (k, _) in enumerate(items) if k == after), len(items))
        items.insert(index, (key, value))
        self.doc["objects"] = dict(items)

    def new_object(self):
        self.commit_form()
        self.capture_history()
        dialog = ctk.CTkInputDialog(title="New object", text="Internal name (from ObjFlow.bin, e.g. kuribo) or object ID (e.g. 0x0191):")
        key = (dialog.get_input() or "").strip()
        if not key:
            return
        try:
            docformat.parse_entry(key, {"notes": "New object"})
        except ValueError as error:
            messagebox.showerror("Invalid object key", str(error), parent=self)
            return
        existing = self.existing_key(key)
        if existing:
            messagebox.showinfo("Already there", f"{existing} is already in the list.")
            key = existing
        else:
            self.insert_after(key, {"description": "Describe what the object does."}, self.selected)
        self.selected = key
        self.refresh_all()
        self.capture_history()

    def duplicate_object(self):
        if self.selected is None:
            return
        self.commit_form()
        self.capture_history()
        key = self.unique_key(f"{self.selected}_copy")
        self.insert_after(key, copy.deepcopy(self.objects[self.selected]), self.selected)
        self.selected = key
        self.refresh_all()
        self.capture_history()

    def delete_object(self):
        self.commit_form()
        self.capture_history()
        if self.selected is None or not messagebox.askyesno("Delete object", f"Delete the documentation of {self.selected}?"):
            return
        keys = list(self.objects)
        i = keys.index(self.selected)
        del self.objects[self.selected]
        rest = list(self.objects)
        self.selected = rest[min(i, len(rest) - 1)] if rest else None
        self.refresh_all()
        self.capture_history()

    # -- form --

    def set_status(self, text: str, color: str = MUTED):
        self.status.configure(text=text, text_color=color)

    def build_form(self):
        if self.form_built:
            self.populate_form()
            return
        self.form_loading = True
        for child in self.form.winfo_children():
            child.destroy()
        self.fields: dict = {}
        key = self.selected
        if key is None or key not in self.objects:
            label(self.form, "No object selected. Choose one on the left, or + New object.", 13).grid(row=0, column=0, sticky="w", padx=4, pady=8)
            self.form_loading = False
            return
        entry_ = self.objects[key] if isinstance(self.objects[key], dict) else {}

        # Object
        box = card(self.form)
        box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        box.grid_columnconfigure(1, weight=1)
        label(box, "Object", 14, TEXT, "bold").grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 6))
        self.key_entry = self.row_entry(box, 1, "Key", key, "Internal name, decimal ID or 0x ID")
        self.key_entry.bind("<Return>", lambda e: self.rename())
        self.key_entry.bind("<FocusOut>", lambda e: self.rename())
        self.fields["label"] = self.row_entry(box, 2, "Label", entry_.get("label", ""), "Name shown in the editor (optional)")
        self.fields["description"] = self.row_text(box, 3, "Description", entry_.get("description", ""), 84)
        self.fields["notes"] = self.row_text(box, 4, "Notes", entry_.get("notes", ""), 56)
        label(box, "Notes are shown highlighted under the description: requirements, known problems…", 11, FAINT).grid(row=5, column=1, sticky="w", padx=(0, 14), pady=(0, 12))

        # How well it is documented
        box = card(self.form)
        box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        box.grid_columnconfigure(1, weight=1)
        label(box, "How well it is documented", 14, TEXT, "bold").grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 6))
        label(box, "Status", 12).grid(row=1, column=0, sticky="w", padx=14, pady=4)
        names = {"": "Estimated", "documented": "Documented", "partial": "Partially documented", "unknown": "Unknown"}
        self.status_menu = ctk.CTkSegmentedButton(box, values=list(names.values()), command=lambda _: self.commit_form(), font=font(12), height=30,
                                                  fg_color=FIELD, selected_color=HOVER, selected_hover_color=HOVER, unselected_color=FIELD,
                                                  unselected_hover_color=HOVER, text_color=TEXT)
        self.status_menu.set(names.get(str(entry_.get("status", "")), "Estimated"))
        self.status_menu.grid(row=1, column=1, sticky="w", padx=(0, 14), pady=4)
        self.status_names = {v: k for k, v in names.items()}
        self.fields["documented"] = self.row_entry(box, 2, "Documented %", str(entry_.get("documented", "")), "0–100, or empty to estimate", width=200)
        self.shown_as = label(box, "", 11, FAINT)
        self.shown_as.grid(row=3, column=1, sticky="w", padx=(0, 14), pady=(0, 12))

        # Settings
        box = card(self.form)
        box.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        box.grid_columnconfigure(0, weight=1)
        label(box, "Settings 1–8", 14, TEXT, "bold").grid(row=0, column=0, sticky="w", padx=14, pady=(12, 0))
        label(box, "Tick a setting to document it; a documented setting needs a label. Leave the others empty when their meaning is not known.", 11, FAINT
              ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 6))
        settings = entry_.get("settings") if isinstance(entry_.get("settings"), dict) else {}
        self.setting_fields = {}
        for i in range(1, 9):
            self.build_setting(box, i + 1, str(i), settings.get(str(i)))
        ctk.CTkFrame(box, fg_color=CARD, height=6).grid(row=10, column=0)
        self.form_loading = False
        self.form_built = True
        self.update_shown_as()
        self.form._parent_canvas.yview_moveto(0)

    def populate_form(self, reset_scroll=True):
        """Reuse the editor widgets when selecting another object or toggling a setting."""
        self.form_loading = True
        if self.selected is None or self.selected not in self.objects:
            for child in self.form.winfo_children():
                child.grid_remove()
            self.form_loading = False
            return
        for child in self.form.winfo_children():
            child.grid()
        record = self.objects[self.selected]
        record = record if isinstance(record, dict) else {}

        def assign(field, value, multiline=False):
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if multiline:
                if field.get("1.0", "end-1c") != text:
                    field.delete("1.0", "end")
                    field.insert("1.0", text)
            elif field.get() != text:
                field.delete(0, "end")
                field.insert(0, text)

        assign(self.key_entry, self.selected)
        for name in ("label", "description", "notes", "documented"):
            assign(self.fields[name], record.get(name, ""), name in ("description", "notes"))
        names = {"documented": "Documented", "partial": "Partially documented", "unknown": "Unknown"}
        self.status_menu.set(names.get(str(record.get("status", "")), "Estimated"))
        settings = record.get("settings")
        settings = settings if isinstance(settings, dict) else {}
        for index, fields in self.setting_fields.items():
            setting = settings.get(index)
            setting = setting if isinstance(setting, dict) else None
            enabled = setting is not None
            fields["on"].set(enabled)
            fields["head"].configure(text=f"Setting {index}" + (f" · {setting.get('label')}" if setting and setting.get("label") else ""))
            fields["frame"].configure(fg_color=FIELD if enabled else CARD)
            if enabled and "label" not in fields:
                self.build_setting_details(fields["frame"], index, setting, fields)
            for child in fields.get("details", []):
                child.grid() if enabled else child.grid_remove()
            if not enabled:
                continue
            for name in ("label", "description", "values", "limits", "min", "max"):
                assign(fields[name], setting.get(name, ""), name == "description")
            assign(fields["options"], options_to_text(setting.get("options")), True)
            for flag in ("signed", "otherValues"):
                fields[flag].set(bool(setting.get(flag)))
        self.form_loading = False
        self.update_shown_as()
        if reset_scroll:
            self.form._parent_canvas.yview_moveto(0)

    def row_entry(self, master, row: int, name: str, value: str, placeholder: str = "", width: int | None = None) -> ctk.CTkEntry:
        label(master, name, 12).grid(row=row, column=0, sticky="nw", padx=14, pady=5)
        field = entry(master, placeholder_text=placeholder, **({"width": width} if width else {}))
        if value:
            field.insert(0, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        field.grid(row=row, column=1, sticky="w" if width else "ew", padx=(0, 14), pady=4)
        field.bind("<KeyRelease>", self.queue_form_commit)
        return field

    def row_text(self, master, row: int, name: str, value: str, height: int) -> ctk.CTkTextbox:
        label(master, name, 12).grid(row=row, column=0, sticky="nw", padx=14, pady=5)
        field = textbox(master, height)
        field.insert("1.0", value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        field.grid(row=row, column=1, sticky="ew", padx=(0, 14), pady=4)
        field.bind("<KeyRelease>", self.queue_form_commit)
        return field

    def build_setting(self, master, row: int, index: str, setting: dict | None):
        setting = setting if isinstance(setting, dict) else None
        frame = ctk.CTkFrame(master, fg_color=FIELD if setting else CARD, corner_radius=6, border_width=1, border_color=BORDER)
        frame.grid(row=row, column=0, sticky="ew", padx=14, pady=4)
        frame.grid_columnconfigure(1, weight=1)
        on = tk.BooleanVar(value=setting is not None)
        head = ctk.CTkCheckBox(frame, text=f"Setting {index}" + (f" · {setting.get('label')}" if setting and setting.get("label") else ""),
                               variable=on, font=font(13, "bold"), text_color=TEXT, fg_color=PRIMARY, hover_color="#d4d4d8",
                               checkmark_color=PRIMARY_TEXT, border_color=FAINT, command=lambda: self.toggle_setting(index, on.get()))
        head.grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=8)
        fields = {"on": on, "head": head, "frame": frame}
        self.setting_fields[index] = fields
        if not setting:
            return
        self.build_setting_details(frame, index, setting, fields)

    def build_setting_details(self, frame, index, setting, fields):
        before = set(frame.winfo_children())
        fields["label"] = self.row_entry(frame, 1, "Label", setting.get("label", ""), "Required")
        fields["description"] = self.row_text(frame, 2, "Description", setting.get("description", ""), 48)
        fields["values"] = self.row_entry(frame, 3, "Values", setting.get("values", ""), "A note on the values (optional)")
        fields["limits"] = self.row_entry(frame, 4, "Limits", setting.get("limits", ""), "A note on the limits (optional)")
        line = ctk.CTkFrame(frame, fg_color=FIELD)
        line.grid(row=5, column=1, sticky="w", padx=(0, 14), pady=4)
        label(frame, "Range", 12).grid(row=5, column=0, sticky="nw", padx=14, pady=5)
        fields["signed"] = tk.BooleanVar(value=bool(setting.get("signed")))
        ctk.CTkCheckBox(line, text="Signed (−32768–32767)", variable=fields["signed"], font=font(12), text_color=TEXT, fg_color=PRIMARY,
                        hover_color="#d4d4d8", checkmark_color=PRIMARY_TEXT, border_color=FAINT, command=self.commit_form).pack(side="left", padx=(0, 12))
        label(line, "Min", 12).pack(side="left", padx=(0, 4))
        fields["min"] = entry(line, width=90, placeholder_text="none")
        if "min" in setting:
            fields["min"].insert(0, str(setting["min"]))
        fields["min"].pack(side="left", padx=(0, 10))
        fields["min"].bind("<KeyRelease>", self.queue_form_commit)
        label(line, "Max", 12).pack(side="left", padx=(0, 4))
        fields["max"] = entry(line, width=90, placeholder_text="none")
        if "max" in setting:
            fields["max"].insert(0, str(setting["max"]))
        fields["max"].pack(side="left")
        fields["max"].bind("<KeyRelease>", self.queue_form_commit)
        fields["options"] = self.row_text(frame, 6, "Choices", options_to_text(setting.get("options")), 70)
        label(frame, 'One "value = label" per line, e.g. 0 = Off. With choices the setting becomes a list in the editor.', 11, FAINT
              ).grid(row=7, column=1, sticky="w", padx=(0, 14))
        fields["otherValues"] = tk.BooleanVar(value=bool(setting.get("otherValues")))
        ctk.CTkCheckBox(frame, text="Other values allowed (the list also offers “Other value…”)", variable=fields["otherValues"], font=font(12),
                        text_color=TEXT, fg_color=PRIMARY, hover_color="#d4d4d8", checkmark_color=PRIMARY_TEXT, border_color=FAINT,
                        command=self.commit_form).grid(row=8, column=1, sticky="w", padx=(0, 14), pady=(4, 10))
        fields["details"] = [child for child in frame.winfo_children() if child not in before]

    def toggle_setting(self, index: str, on: bool):
        self.capture_history()
        self.commit_form()
        entry_ = self.objects[self.selected]
        settings = entry_.setdefault("settings", {})
        if on:
            settings[index] = {"label": f"Setting {index}"}
        else:
            settings.pop(index, None)
        if not settings:
            entry_.pop("settings", None)
        else:
            entry_["settings"] = dict(sorted(settings.items()))
        self.populate_form(reset_scroll=False)
        self.refresh_list()
        self.capture_history()

    def rename(self):
        if self.form_loading or self.selected is None:
            return True
        new = self.key_entry.get().strip()
        if new == self.selected:
            return True
        if not new:
            self.key_entry.insert(0, self.selected)
            return False
        try:
            docformat.parse_entry(new, {"notes": "Renamed object"})
        except ValueError as error:
            messagebox.showerror("Invalid object key", str(error), parent=self)
            self.key_entry.delete(0, "end")
            self.key_entry.insert(0, self.selected)
            return False
        existing = self.existing_key(new)
        if existing and existing != self.selected:
            messagebox.showinfo("Already there", f"{new} is already in the list.")
            self.key_entry.delete(0, "end")
            self.key_entry.insert(0, self.selected)
            return False
        self.capture_history()
        self.doc["objects"] = {(new if k == self.selected else k): v for k, v in self.objects.items()}
        self.selected = new
        self.refresh_list()
        self.capture_history()
        return True

    def commit_form(self):
        """Writes the form into the document (empty fields are left out of the file)."""
        if self.form_commit_job:
            self.after_cancel(self.form_commit_job)
            self.form_commit_job = None
        if self.form_loading or self.selected is None or self.selected not in self.objects or not getattr(self, "fields", None):
            return
        entry_ = self.objects[self.selected]
        if not isinstance(entry_, dict):
            entry_ = self.objects[self.selected] = {}

        def put(target: dict, name: str, value):
            if value in (None, "") or value == {}:
                target.pop(name, None)
            else:
                target[name] = value

        try:
            put(entry_, "label", self.fields["label"].get().strip())
            put(entry_, "description", self.fields["description"].get("1.0", "end").strip())
            put(entry_, "notes", self.fields["notes"].get("1.0", "end").strip())
            put(entry_, "status", self.status_names.get(self.status_menu.get(), ""))
            put(entry_, "documented", number_or_text(self.fields["documented"].get()))
            settings = {}
            for index, f in self.setting_fields.items():
                if not f["on"].get():
                    continue
                if "label" not in f:  # just ticked: the form is rebuilt with its fields
                    settings[index] = (entry_.get("settings") or {}).get(index, {"label": f"Setting {index}"})
                    continue
                old = entry_.get("settings")
                old = old.get(index, {}) if isinstance(old, dict) else {}
                s: dict = copy.deepcopy(old) if isinstance(old, dict) else {}
                put(s, "label", f["label"].get().strip())
                put(s, "description", f["description"].get("1.0", "end").strip())
                put(s, "values", f["values"].get().strip())
                put(s, "limits", f["limits"].get().strip())
                if "signed" in s or f["signed"].get():
                    s["signed"] = f["signed"].get()
                put(s, "min", number_or_text(f["min"].get()))
                put(s, "max", number_or_text(f["max"].get()))
                put(s, "options", text_to_options(f["options"].get("1.0", "end")))
                if "otherValues" in s or f["otherValues"].get():
                    s["otherValues"] = f["otherValues"].get()
                settings[index] = s
            put(entry_, "settings", settings)
            # Field order as in the editor's files.
            order = ["label", "description", "notes", "status", "documented", "settings"]
            self.objects[self.selected] = {k: entry_[k] for k in order if k in entry_} | {k: v for k, v in entry_.items() if k not in order}
        except tk.TclError:
            return  # the form is being rebuilt
        self.refresh_list()
        self.update_shown_as()
        self.schedule_history()

    def update_shown_as(self):
        if self.selected is None or not hasattr(self, "shown_as"):
            return
        state, percent, estimated = docformat.status(self.objects.get(self.selected))
        text = f"Shown in the editor as: {docformat.STATUS_LABELS.get(state, state)} · {'~' if estimated else ''}{percent}%"
        if estimated:
            text += " (estimated: half for the description, half for the named settings)"
        problem = self.errors.get(self.selected)
        self.shown_as.configure(text=f"{text}\nProblem: {problem}" if problem else text, text_color=DANGER if problem else FAINT)

    # -- GitHub --

    def preview(self):
        self.commit_form()
        if self.selected is not None:
            PreviewDialog(self, self.selected, self.objects[self.selected])

    def open_propose(self):
        self.commit_form()
        if not self.rename():
            return
        problem = self.check()
        if problem:
            messagebox.showerror("Fix the problem first", f"{problem}\n\nOnly a file the editor accepts can be proposed.")
            return
        ProposeDialog(self)


from .dialogs import ConflictDialog, PreviewDialog, ProposeDialog


def main():
    if os.name == "nt":
        try:  # sharp text on scaled displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()
