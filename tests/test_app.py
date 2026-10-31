"""Real Tk form checks. Skipped on CI without a display; run during the Windows build."""

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from objinfo import docformat
from objinfo.app import App
from objinfo.dialogs import ProposeDialog
from objinfo.github import GitHubError, Snapshot, snapshot
from objinfo.local_editor import LocalDocumentation

BASE = {"version": 1, "objects": {"box": {"description": "Before", "status": "partial", "documented": 50}}}


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk needs a graphical display")
class Form(unittest.TestCase):
    def setUp(self):
        self.start = patch.object(App, "load_start")
        self.start.start()
        self.remote = patch("objinfo.app.snapshot", return_value=Snapshot(BASE, "head", "blob"))
        self.remote.start()
        self.app = App()
        self.app.withdraw()
        self.app.load_text(docformat.dumps(BASE), None, "Test fixture")

    def tearDown(self):
        for event in self.app.tk.call("after", "info"):
            self.app.tk.call("after", "cancel", event)
        self.app.destroy()
        self.remote.stop()
        self.start.stop()

    def test_live_invalid_percentage_can_be_fixed(self):
        field = self.app.fields["documented"]
        field.delete(0, "end")
        field.insert(0, "oops")
        self.app.commit_form()
        self.assertIn("box", self.app.errors)
        self.assertIn("Problem", self.app.shown_as.cget("text"))
        field.delete(0, "end")
        field.insert(0, "60")
        self.app.commit_form()
        self.assertFalse(self.app.errors)
        self.assertEqual(self.app.objects["box"]["documented"], 60)

    def test_undo_redo_and_new_edit_after_undo(self):
        self.app.fields["description"].insert("end", " changed")
        self.app.commit_form()
        self.app.undo()
        self.assertEqual(self.app.objects["box"]["description"], "Before")
        self.app.redo()
        self.assertEqual(self.app.objects["box"]["description"], "Before changed")
        self.app.undo()
        self.app.fields["notes"].insert("end", "New direction")
        self.app.redo()
        self.assertEqual(self.app.objects["box"]["description"], "Before")
        self.assertEqual(self.app.objects["box"]["notes"], "New direction")

    def test_save_retains_baseline_and_unsaved_form_input(self):
        self.app.fields["notes"].insert("end", "Verified in game")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "objects.json"
            self.assertTrue(self.app.write(path))
            self.assertFalse(self.app.dirty)
            self.assertEqual(docformat.loads(path.read_text(encoding="utf-8"))["objects"]["box"]["notes"], "Verified in game")
            self.assertEqual(self.app.baseline, BASE)

    def test_save_commits_a_key_edited_without_losing_focus(self):
        self.app.key_entry.delete(0, "end")
        self.app.key_entry.insert(0, "renamed_box")
        self.assertTrue(self.app.dirty)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "objects.json"
            self.assertTrue(self.app.write(path))
            self.assertIn("renamed_box", docformat.loads(path.read_text(encoding="utf-8"))["objects"])
            self.assertFalse(self.app.dirty)

    def test_switching_objects_reuses_fields_and_preserves_settings(self):
        document = {"version": 1, "objects": {
            "first": {"description": "First", "settings": {"2": {"label": "Choice", "options": {"0": "Off", "1": "On"}}}},
            "second": {"notes": "Second", "settings": {"7": {"label": "Offset", "signed": True, "min": -10}}},
        }}
        self.app.load_text(docformat.dumps(document), None, "Fixture")
        field = self.app.fields["description"]
        self.app.listbox.selection_clear(0, "end")
        self.app.listbox.selection_set(1)
        self.app.on_select()
        self.assertEqual(self.app.selected, "second")
        self.assertEqual(self.app.listbox.curselection(), (1,))
        self.assertIs(self.app.fields["description"], field)
        self.assertFalse(self.app.setting_fields["2"]["on"].get())
        self.assertTrue(self.app.setting_fields["7"]["on"].get())
        self.app.commit_form()
        self.assertEqual(self.app.doc, document)
        self.app.selected = "first"
        self.app.build_form()
        self.assertEqual(self.app.setting_fields["2"]["options"].get("1.0", "end").strip(), "0 = Off\n1 = On")

    def test_save_flushes_deferred_typing_and_leaves_no_pending_callback(self):
        self.app.fields["notes"].insert("end", "Pending edit")
        self.app.queue_form_commit()
        self.app.queue_form_commit()
        self.assertTrue(self.app.dirty)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "objects.json"
            self.assertTrue(self.app.write(path))
            self.assertIsNone(self.app.form_commit_job)
            self.assertEqual(docformat.loads(path.read_text(encoding="utf-8"))["objects"]["box"]["notes"], "Pending edit")

    def test_enabling_and_disabling_setting_keeps_other_input(self):
        field = self.app.fields["notes"]
        field.insert("end", "Keep this text")
        self.app.toggle_setting("7", True)
        self.assertIs(self.app.fields["notes"], field)
        self.assertIn("7", self.app.objects["box"]["settings"])
        self.app.setting_fields["7"]["on"].set(False)
        self.app.toggle_setting("7", False)
        self.assertNotIn("settings", self.app.objects["box"])
        self.assertEqual(self.app.objects["box"]["notes"], "Keep this text")

    def test_remote_banner_distinguishes_local_edits_updates_and_unknown(self):
        self.app.latest_snapshot = Snapshot(copy.deepcopy(BASE), "head", "blob")
        self.app.refresh_remote()
        self.assertIn("up to date", self.app.remote_label.cget("text"))
        self.app.fields["notes"].insert("end", "My test")
        self.app.commit_form()
        self.assertIn("local edits", self.app.remote_label.cget("text"))
        self.app.latest_snapshot.document["objects"]["coin"] = {"notes": "New"}
        self.app.refresh_remote()
        self.assertIn("New documentation available", self.app.remote_label.cget("text"))
        self.app.latest_snapshot = None
        self.app.remote_error = "Network unavailable"
        self.app.refresh_remote()
        self.assertIn("offline", self.app.remote_label.cget("text"))
        self.assertNotIn("up to date", self.app.remote_label.cget("text"))

    def test_proposal_previews_remote_changes_and_disables_empty_submission(self):
        def immediate(work, done, failed):
            done(Snapshot(copy.deepcopy(BASE), "reviewed", "blob") if work is snapshot else "Contributor")
        with patch.object(self.app, "background", side_effect=immediate):
            dialog = ProposeDialog(self.app)
            self.assertEqual(dialog.go.cget("state"), "disabled")
            self.assertIn("No changes", dialog.changes.cget("text"))
            dialog.destroy()
            self.app.fields["notes"].insert("end", "Verified in game")
            self.app.commit_form()
            dialog = ProposeDialog(self.app)
            self.assertEqual(dialog.go.cget("state"), "normal")
            self.assertEqual(dialog.latest.commit, "reviewed")
            self.assertEqual(dialog.prepared["objects"]["box"]["notes"], "Verified in game")
            dialog.destroy()

    def test_direct_proposal_uses_connected_account_and_opens_the_created_pr(self):
        self.app.fields["notes"].insert("end", "Verified change")
        self.app.commit_form()
        def immediate(work, done, failed):
            done(Snapshot(copy.deepcopy(BASE), "reviewed", "blob") if work is snapshot else work())
        with patch("objinfo.dialogs.cli_account", return_value="Contributor"), patch.object(self.app, "background", side_effect=immediate), \
                patch("objinfo.dialogs.propose", return_value="https://github.com/example/pull/1") as propose, patch("objinfo.dialogs.webbrowser.open") as browser:
            dialog = ProposeDialog(self.app)
            dialog.automatic()
            self.assertTrue(dialog.submitted)
            self.assertEqual(propose.call_args.kwargs["expected_login"], "Contributor")
            self.assertFalse(propose.call_args.kwargs["game_tested"])
            browser.assert_called_once_with("https://github.com/example/pull/1")
            dialog.destroy()

    def test_import_editor_settings_loads_a_copy_and_retains_the_baseline(self):
        document = copy.deepcopy(BASE)
        document["objects"]["box"]["notes"] = "From editor"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"preserve":"all settings"}', encoding="utf-8")
            source = LocalDocumentation(document, BASE, path, "Editor documentation")
            self.assertTrue(self.app.import_editor_documentation(source))
            self.assertEqual(self.app.doc, document)
            self.assertEqual(self.app.baseline, BASE)
            self.assertIsNone(self.app.path)
            self.assertEqual(path.read_text(encoding="utf-8"), '{"preserve":"all settings"}')

    def test_proposal_validator_runs_automatically_and_blocks_invalid_submission(self):
        self.app.fields["notes"].insert("end", "Changed")
        self.app.commit_form()
        def immediate(work, done, failed):
            done(Snapshot(copy.deepcopy(BASE), "reviewed", "blob") if work is snapshot else "Contributor")
        with patch.object(self.app, "background", side_effect=immediate), patch("objinfo.dialogs.propose") as propose:
            dialog = ProposeDialog(self.app)
            self.assertIn("Validator passed", dialog.validation_label.cget("text"))
            dialog.prepared["objects"]["box"]["documented"] = 101
            dialog.automatic()
            self.assertIn("Validator failed", dialog.validation_label.cget("text"))
            self.assertIn("box.documented", dialog.validation_label.cget("text"))
            self.assertEqual(dialog.go.cget("state"), "disabled")
            propose.assert_not_called()
            dialog.destroy()
