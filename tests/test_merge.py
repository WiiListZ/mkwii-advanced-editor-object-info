import copy
import tempfile
import unittest
from pathlib import Path

from objinfo import docformat
from objinfo.merge import MISSING, changes, merge, resolve
from objinfo.storage import read_baseline, save_document


def document(**objects):
    return {"version": 1, "objects": objects}


class Merge(unittest.TestCase):
    def test_independent_fields_and_objects_are_preserved(self):
        base = document(box={"description": "Before", "settings": {"1": {"label": "Speed", "min": 0}}}, sun={"notes": "Old"})
        local, remote = copy.deepcopy(base), copy.deepcopy(base)
        local["objects"]["box"]["description"] = "My test"
        remote["objects"]["box"]["settings"]["1"]["max"] = 40
        remote["objects"]["sun"]["notes"] = "New"
        remote["objects"]["coin"] = {"notes": "Added"}
        result, conflicts = merge(base, local, remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(result["objects"]["box"]["description"], "My test")
        self.assertEqual(result["objects"]["box"]["settings"]["1"]["max"], 40)
        self.assertEqual(result["objects"]["sun"], remote["objects"]["sun"])
        self.assertIn("coin", result["objects"])
        self.assertEqual(base["objects"]["sun"]["notes"], "Old")

    def test_same_field_conflict_is_explicit_and_resolvable(self):
        result, conflicts = merge(document(box={"notes": "Original"}), document(box={"notes": "Mine"}), document(box={"notes": "Theirs"}))
        self.assertEqual([c.name for c in conflicts], ["objects.box.notes"])
        self.assertEqual(result["objects"]["box"]["notes"], "Mine")
        resolve(result, conflicts[0], False)
        self.assertEqual(result["objects"]["box"]["notes"], "Theirs")

    def test_deletion_versus_remote_edit_and_concurrent_additions(self):
        result, conflicts = merge(document(box={"notes": "Original"}), document(), document(box={"notes": "Theirs"}))
        self.assertIs(conflicts[0].local, MISSING)
        resolve(result, conflicts[0], False)
        self.assertIn("box", result["objects"])
        result, conflicts = merge(document(), document(box={"notes": "Mine"}), document(box={"notes": "Theirs"}))
        self.assertEqual(len(conflicts), 1)
        self.assertIs(conflicts[0].base, MISSING)

    def test_remote_deletions_and_local_additions_survive(self):
        result, conflicts = merge(document(box={"notes": "Same"}), document(box={"notes": "Same"}, coin={"notes": "Mine"}), document())
        self.assertEqual(result, document(coin={"notes": "Mine"}))
        self.assertFalse(conflicts)

    def test_identical_edits_do_not_conflict(self):
        same = document(box={"notes": "Both"})
        self.assertEqual(merge(document(box={"notes": "Old"}), same, same), (same, []))

    def test_save_and_reopen_retain_original_baseline(self):
        base, local = document(box={"notes": "Before"}), document(box={"notes": "Mine"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "objects.json"
            save_document(path, local, base)
            self.assertEqual(docformat.loads(path.read_text(encoding="utf-8")), local)
            reopened_base = read_baseline(path, document())
            self.assertEqual(reopened_base, base)
            result, conflicts = merge(reopened_base, local, document(box={"notes": "Before"}, coin={"notes": "New"}))
            self.assertFalse(conflicts)
            self.assertEqual(changes(document(box={"notes": "Before"}, coin={"notes": "New"}), result)["changed"], ["box"])
