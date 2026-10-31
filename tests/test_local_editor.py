import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from objinfo import docformat
from objinfo.local_editor import find_local_documentation, read_local_documentation, settings_candidates

BASE = {"version": 1, "objects": {"box": {"notes": "Base"}}}
LOCAL = {"version": 1, "objects": {"box": {"notes": "Local test"}}}


class LocalEditor(unittest.TestCase):
    def test_custom_documentation_takes_priority_and_retains_its_base(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = {"unrelated": {"keep": True}, "customObjectDocumentation": {"name": "My notes", "objects": LOCAL["objects"], "base": BASE["objects"]},
                        "objectDocumentationOnline": {"json": BASE}}
            original = json.dumps(settings)
            path.write_text(original, encoding="utf-8")
            result = read_local_documentation(path)
            self.assertEqual(result.document, LOCAL)
            self.assertEqual(result.baseline, BASE)
            self.assertFalse(result.standalone)
            self.assertIn("My notes", result.description)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_cached_default_and_exported_json_are_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"objectDocumentationOnline": {"json": BASE}}), encoding="utf-8")
            result = read_local_documentation(path)
            self.assertEqual(result.document, BASE)
            self.assertEqual(result.baseline, BASE)
            path.write_text(docformat.dumps(LOCAL), encoding="utf-8")
            self.assertTrue(read_local_documentation(path).standalone)

    def test_missing_documentation_is_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"someOtherSetting":true}', encoding="utf-8")
            self.assertIsNone(read_local_documentation(path))
            with patch("objinfo.local_editor.settings_candidates", return_value=[Path(folder) / "missing.json", path]):
                self.assertIsNone(find_local_documentation())

    def test_explicit_settings_directory_is_searched_first(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"MKWII_SETTINGS_DIR": folder}):
            self.assertEqual(settings_candidates()[0], Path(folder) / "settings.json")

    def test_invalid_settings_or_documentation_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"objectDocumentationOnline":{"json":{"version":2,"objects":{}}}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                read_local_documentation(path)
