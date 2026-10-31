"""The format rules, the same as MKWii Advanced Editor's (tests/object-documentation.test.ts there)."""

import json
import unittest
from pathlib import Path

from objinfo import docformat
from objinfo.app import options_to_text, text_to_options

ROOT = Path(__file__).resolve().parent.parent


def parse(objects: dict) -> dict:
    return docformat.parse({"version": 1, "objects": objects})


class Format(unittest.TestCase):
    def test_repository_file_is_valid_and_formatted(self):
        text = (ROOT / "data" / "objects.json").read_text(encoding="utf-8")
        objects = docformat.parse(json.loads(text))
        self.assertGreaterEqual(len(objects), 40)
        self.assertEqual(text, docformat.dumps(json.loads(text)))
        self.assertEqual(objects["itembox"]["settings"]["2"]["options"][1], "Banana")

    def test_keys_are_normalised(self):
        objects = parse({"0x0065": {"label": "Box"}, "0100": {"description": "Another"}, "itembox": {"notes": "n"}})
        self.assertEqual(set(objects), {"101", "100", "itembox"})

    def test_rejected_records(self):
        bad = [
            {"version": 2, "objects": {}},
            {"version": 1, "objects": {}},
            {"version": 1, "objects": {"itembox": {"settings": {"9": {"label": "Bad"}}}}},
            {"version": 1, "objects": {"0x10000": {"label": "Too large"}}},
            {"version": 1, "objects": {"itembox": {"settings": {"2": {"label": "Item", "limits": 10}}}}},
            {"version": 1, "objects": {"itembox": {}}},
            {"version": 1, "objects": {"bad key!": {"label": "x"}}},
            {"version": 1, "objects": {"kuribo": {"status": "done"}}},
            {"version": 1, "objects": {"kuribo": {"documented": 101}}},
            {"version": 1, "objects": {"kuribo": {"documented": 12.5}}},
            {"version": 1, "objects": {"kuribo": {"documented": True}}},
            {"version": 1, "objects": {"kuribo": {"status": "documented", "documented": 80}}},
            {"version": 1, "objects": {"kuribo": {"label": "   "}}},
        ]
        for document in bad:
            with self.subTest(document=document), self.assertRaises(docformat.DocumentationError):
                docformat.parse(document)

    def test_setting_limits_and_choices(self):
        car = parse({"car_body": {"settings": {
            "1": {"label": "Speed", "min": 0, "max": 120},
            "2": {"label": "Offset", "signed": True, "min": -500, "max": 500},
            "4": {"label": "Colour", "options": {"0": "Blue", "1": "Red"}, "otherValues": True},
        }}})["car_body"]["settings"]
        self.assertEqual(car["2"]["min"], -500)
        self.assertEqual(car["4"]["options"], {0: "Blue", 1: "Red"})

        def bad(setting):
            return lambda: parse({"x": {"settings": {"1": {"label": "S", **setting}}}})
        for setting in [{"min": -1}, {"max": 70000}, {"signed": True, "min": -40000}, {"min": 5, "max": 2}, {"signed": "yes"},
                        {"options": {}}, {"options": {"a": "A"}}, {"options": {"5": "Five"}, "max": 3}, {"options": {"1": ""}}, {"min": 1.5}]:
            with self.subTest(setting=setting):
                self.assertRaises(docformat.DocumentationError, bad(setting))

    def test_status_and_percentage(self):
        eight = {str(i): {"label": f"S{i}"} for i in range(1, 9)}
        self.assertEqual(docformat.status({"settings": {}}), ("unknown", 0, True))
        self.assertEqual(docformat.status({"description": "x"}), ("partial", 50, True))
        self.assertEqual(docformat.status({"description": "x", "settings": eight}), ("documented", 100, True))
        self.assertEqual(docformat.status({"status": "documented"}), ("documented", 100, False))
        self.assertEqual(docformat.status({"status": "partial", "documented": 35}), ("partial", 35, False))
        self.assertEqual(docformat.status({"documented": 0})[0], "unknown")
        self.assertEqual(docformat.status({"description": "x", "status": "partial", "settings": eight})[1], 99)

    def test_errors_name_the_object(self):
        with self.assertRaises(docformat.DocumentationError) as caught:
            parse({"kuribo": {"description": "ok"}, "wanwan": {"settings": {"1": {"description": "no label"}}}})
        self.assertEqual(caught.exception.key, "wanwan")
        self.assertIn("wanwan.settings.1.label", str(caught.exception))

    def test_invalid_json_is_not_silently_repaired(self):
        for text in ['{"version":1,"version":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                docformat.loads(text)
        with self.assertRaises(ValueError):
            docformat.parse({"version": True, "objects": {"x": {"notes": "x"}}})

    def test_live_status_never_crashes_on_invalid_form_values(self):
        for value in ["", "abc", 200, -1, [], {}, True, None]:
            with self.subTest(value=value):
                state, percent, estimated = docformat.status({"status": [], "documented": value, "settings": "invalid"})
                self.assertIn(state, ("unknown", "partial", "documented"))
                self.assertTrue(0 <= percent <= 100)

    def test_estimates_round_like_the_main_editor(self):
        self.assertEqual(docformat.status({"settings": {"1": {"label": "One"}, "2": {"label": "Two"}}})[1], 13)


class Choices(unittest.TestCase):
    def test_duplicate_choices_remain_an_error(self):
        options = text_to_options("1 = First\n01 = Second")
        with self.assertRaises(ValueError):
            parse({"box": {"settings": {"1": {"label": "Choice", "options": options}}}})

    def test_choices_as_text_round_trip(self):
        options = {"0": "Default", "1": "Banana", "-2": "Back"}
        self.assertEqual(text_to_options(options_to_text(options)), options)
        self.assertEqual(text_to_options("3: Star\n\n 7 =  Green Shell "), {"3": "Star", "7": "Green Shell"})
        self.assertIsNone(text_to_options("  \n"))
        # A line without a number is kept, so the check can point at it.
        self.assertEqual(text_to_options("Banana"), {"Banana": ""})


if __name__ == "__main__":
    unittest.main()
