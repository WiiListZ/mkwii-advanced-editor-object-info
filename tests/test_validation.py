import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from objinfo import docformat
from objinfo.validation import validate_document
from scripts.validate import main


class SharedValidator(unittest.TestCase):
    def test_valid_document_reports_object_and_setting_counts(self):
        report = validate_document({"version": 1, "objects": {"box": {"settings": {"2": {"label": "Item type"}}}}})
        self.assertTrue(report.valid)
        self.assertEqual((report.objects, report.settings), (1, 1))
        self.assertIn("Validator passed", report.summary)

    def test_all_invalid_objects_are_reported(self):
        report = validate_document({"version": 1, "objects": {"box": {"documented": 101}, "sun": {"settings": {"9": {"label": "Invalid slot"}}}}})
        self.assertFalse(report.valid)
        self.assertTrue(any("box.documented" in error for error in report.errors))
        self.assertTrue(any("sun.settings" in error for error in report.errors))

    def test_cli_rejects_the_same_invalid_json_and_writes_a_github_summary(self):
        document = {"version": 1, "objects": {"box": {"documented": 101}}}
        report = validate_document(document)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "objects.json"
            summary = Path(folder) / "summary.md"
            path.write_text(docformat.dumps(document), encoding="utf-8")
            output = io.StringIO()
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(summary)}), contextlib.redirect_stdout(output):
                code = main([str(path)])
            self.assertEqual(code, 1)
            self.assertIn(report.errors[0], output.getvalue())
            self.assertIn("::error file=", output.getvalue())
            self.assertIn("Failed", summary.read_text(encoding="utf-8"))

    def test_cli_accepts_a_valid_document(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "objects.json"
            path.write_text(docformat.dumps({"version": 1, "objects": {"box": {"notes": "Valid"}}}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path)]), 0)
