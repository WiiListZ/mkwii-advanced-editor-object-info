"""Checks object documentation files with the rules of MKWii Advanced Editor.

Usage: python scripts/validate.py [data/objects.json ...]
Exits with 1 and says where when a file would be refused by the editor.
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from objinfo import docformat  # noqa: E402
from objinfo.validation import validate_document  # noqa: E402


def main(paths: list[str]) -> int:
    failed = False
    summary = ["## Object documentation validator", "", "The desktop program and this check use the same validator.", ""]
    for name in paths or ["data/objects.json"]:
        path = Path(name)
        try:
            text = path.read_text(encoding="utf-8-sig")
            document = docformat.loads(text)
            report = validate_document(document)
            if not report.valid:
                raise ValueError("\n".join(report.errors))
        except (OSError, ValueError) as error:
            message = str(error)
            if "GITHUB_ACTIONS" in os.environ:
                escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                print(f"::error file={path}::{escaped}")
            else:
                print(f"{path}: {message}")
            summary += [f"### Failed: `{path}`", "", "```text", message, "```", ""]
            failed = True
            continue
        objects = docformat.parse(document)
        counts = {"documented": 0, "partial": 0, "unknown": 0}
        for entry in objects.values():
            counts[docformat.status(entry)[0]] += 1
        print(f"{path}: valid, {len(objects)} objects ({counts['documented']} documented, {counts['partial']} partial, {counts['unknown']} unknown)")
        summary += [f"### Passed: `{path}`", "", f"{report.objects} objects; {report.settings} documented settings.", ""]
        if text != docformat.dumps(docformat.loads(text)):
            print(f"{path}: note: not formatted as the editor writes it (2 spaces); the Object Info Editor saves it that way.")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write("\n".join(summary) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
