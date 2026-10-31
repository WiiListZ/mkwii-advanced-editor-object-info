"""Atomic saves and a baseline that survives saving and reopening a contribution."""

import json
import os
import tempfile
from pathlib import Path

from . import docformat


def atomic_write(path: Path, text: str):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def baseline_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.objinfo-base.json")


def read_baseline(path: Path, fallback: dict) -> dict:
    try:
        document = docformat.loads(baseline_path(path).read_text(encoding="utf-8-sig"))
        docformat.parse(document)
        return document
    except (OSError, ValueError):
        return json.loads(docformat.dumps(fallback))


def save_document(path: Path, document: dict, baseline: dict):
    # Save the baseline first: a failure must not silently lose the origin of the edits.
    atomic_write(baseline_path(path), docformat.dumps(baseline))
    atomic_write(path, docformat.dumps(document))
