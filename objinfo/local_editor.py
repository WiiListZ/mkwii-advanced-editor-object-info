"""Read the documentation in use by the main editor without modifying its settings."""

import copy
import os
from dataclasses import dataclass
from pathlib import Path

from . import docformat


@dataclass
class LocalDocumentation:
    document: dict
    baseline: dict | None
    path: Path
    description: str
    standalone: bool = False


def read_local_documentation(path: Path) -> LocalDocumentation | None:
    data = docformat.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        return None
    if data.get("version") == 1 and isinstance(data.get("objects"), dict):
        docformat.parse(data)
        return LocalDocumentation(data, None, path, str(path), True)
    custom = data.get("customObjectDocumentation")
    cached = data.get("objectDocumentationOnline")
    cached_doc = cached.get("json") if isinstance(cached, dict) else None
    if isinstance(custom, dict) and isinstance(custom.get("objects"), dict) and custom["objects"]:
        document = {"version": 1, "objects": custom["objects"]}
        base = custom.get("base")
        baseline = {"version": 1, "objects": base} if isinstance(base, dict) and base else cached_doc
        description = f"MKWii Advanced Editor · {custom.get('name') or 'custom documentation'} · {path}"
    elif isinstance(cached_doc, dict):
        document, baseline = cached_doc, cached_doc
        description = f"MKWii Advanced Editor · cached default documentation · {path}"
    else:
        return None
    docformat.parse(document)
    if baseline is not None:
        try:
            docformat.parse(baseline)
        except ValueError:
            baseline = None
    return LocalDocumentation(copy.deepcopy(document), copy.deepcopy(baseline), path, description)


def settings_candidates() -> list[Path]:
    folders = []
    if os.environ.get("MKWII_SETTINGS_DIR"):
        folders.append(Path(os.environ["MKWII_SETTINGS_DIR"]))
    for variable in ("APPDATA", "LOCALAPPDATA", "HOME"):
        if os.environ.get(variable):
            folders.append(Path(os.environ[variable]) / "MKWiiAdvancedEditor")
    folders.append(Path.home() / "MKWiiAdvancedEditor")
    return list(dict.fromkeys(folder / "settings.json" for folder in folders))


def find_local_documentation() -> LocalDocumentation | None:
    for path in settings_candidates():
        if path.is_file():
            result = read_local_documentation(path)
            if result is not None:
                return result
    return None
