"""Checks object documentation files with the rules of MKWii Advanced Editor.

Usage: python scripts/validate.py [data/objects.json ...]
Exits with 1 and says where when a file would be refused by the editor.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from objinfo import docformat  # noqa: E402


def main(paths: list[str]) -> int:
    failed = False
    for name in paths or ["data/objects.json"]:
        path = Path(name)
        try:
            text = path.read_text(encoding="utf-8-sig")
            objects = docformat.parse(docformat.loads(text))
        except (OSError, ValueError) as error:
            print(f"::error file={path}::{error}" if "GITHUB_ACTIONS" in __import__("os").environ else f"{path}: {error}")
            failed = True
            continue
        counts = {"documented": 0, "partial": 0, "unknown": 0}
        for entry in objects.values():
            counts[docformat.status(entry)[0]] += 1
        print(f"{path}: valid, {len(objects)} objects ({counts['documented']} documented, {counts['partial']} partial, {counts['unknown']} unknown)")
        if text != docformat.dumps(docformat.loads(text)):
            print(f"{path}: note: not formatted as the editor writes it (2 spaces); the Object Info Editor saves it that way.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
