"""The object documentation format of MKWii Advanced Editor (data/objects.json).

The rules are the same as the editor's own reader (parseObjectDocumentation in
web/js/data/object-documentation.js), so a file accepted here is accepted by the editor:

    { "version": 1, "objects": { "<key>": { entry }, ... } }

Keys are ObjFlow.bin internal names ("itembox"), decimal IDs ("101") or hexadecimal IDs ("0x0065").
An entry has label, description, notes, status ("documented" | "partial" | "unknown"), documented
(0-100) and settings "1" to "8", each with label (required), description, values, limits, signed,
min, max, options ({ "value": "label" }) and otherValues.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

STATUSES = ("documented", "partial", "unknown")
STATUS_LABELS = {"documented": "Documented", "partial": "Partially documented", "unknown": "Unknown"}
KEY_RE = re.compile(r"^(?:0x[0-9a-f]+|[0-9]+|[A-Za-z_][A-Za-z0-9_.-]*)$", re.IGNORECASE)
NUMERIC_KEY_RE = re.compile(r"^(?:0x[0-9a-f]+|[0-9]+)$", re.IGNORECASE)
OPTION_KEY_RE = re.compile(r"^-?[0-9]+$")


class DocumentationError(ValueError):
    """A rule of the format is broken; the message says where (e.g. "itembox.settings.2.label")."""

    def __init__(self, message: str, key: str | None = None):
        super().__init__(message)
        self.key = key


def _plain(value: Any) -> bool:
    return isinstance(value, dict)


def _integer(value: Any) -> bool:
    # Like JavaScript's Number.isInteger: 5 and 5.0 are whole numbers, true/false are not.
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value.is_integer()


def _clean(value: Any, where: str, maximum: int = 2000, key: str | None = None) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DocumentationError(f"{where} must be a nonempty string of at most {maximum} characters", key)
    return value.strip()


def _setting_input(setting: dict, where: str, key: str) -> dict:
    out: dict[str, Any] = {}
    for flag in ("signed", "otherValues"):
        if flag not in setting:
            continue
        if not isinstance(setting[flag], bool):
            raise DocumentationError(f"{where}.{flag} must be true or false", key)
        out[flag] = setting[flag]
    lo, hi = (-32768, 32767) if out.get("signed") else (0, 65535)

    def whole(value: Any, name: str) -> int:
        if not _integer(value) or value < lo or value > hi:
            raise DocumentationError(f"{where}.{name} must be a whole number from {lo} to {hi}", key)
        return int(value)

    if "min" in setting:
        out["min"] = whole(setting["min"], "min")
    if "max" in setting:
        out["max"] = whole(setting["max"], "max")
    if "min" in out and "max" in out and out["min"] > out["max"]:
        raise DocumentationError(f"{where}.min must not be above max", key)
    if "options" in setting:
        options = setting["options"]
        if not _plain(options):
            raise DocumentationError(f'{where}.options must be an object such as {{ "0": "Off", "1": "On" }}', key)
        if not options or len(options) > 256:
            raise DocumentationError(f"{where}.options must have 1 to 256 choices", key)
        parsed: dict[int, str] = {}
        for value, label in options.items():
            if not OPTION_KEY_RE.match(value):
                raise DocumentationError(f"{where}.options key {value} must be a whole number", key)
            n = whole(int(value), f"options key {value}")
            if ("min" in out and n < out["min"]) or ("max" in out and n > out["max"]):
                raise DocumentationError(f"{where}.options key {value} is outside min–max", key)
            parsed[n] = _clean(label, f"{where}.options.{value}", 120, key)
        out["options"] = parsed
    return out


def normalize_key(key: str) -> str:
    """"0x0065" and "0101" become "101"; names stay as they are."""
    if NUMERIC_KEY_RE.match(key):
        return str(int(key, 16) if key.lower().startswith("0x") else int(key))
    return key


def parse(document: Any) -> dict[str, dict]:
    """Checks a whole documentation and returns its entries by normalised key.

    Raises DocumentationError on the first problem, with the object key in `.key` when there is one.
    """
    if not _plain(document) or isinstance(document.get("version"), bool) or document.get("version") != 1 or not _plain(document.get("objects")):
        raise DocumentationError('Expected { "version": 1, "objects": { ... } }')
    entries = document["objects"]
    if not entries or len(entries) > 1000:
        raise DocumentationError("Provide 1 to 1000 object entries")
    objects: dict[str, dict] = {}
    for key, value in entries.items():
        objects[normalize_key(key) if KEY_RE.match(key) else key] = parse_entry(key, value)
    return objects


def parse_entry(key: str, value: Any) -> dict:
    """Checks one object entry (its key and its fields)."""
    if not KEY_RE.match(key):
        raise DocumentationError(f"Invalid object key: {key}", key)
    if NUMERIC_KEY_RE.match(key) and int(normalize_key(key)) > 65535:
        raise DocumentationError(f"{key} must be a 16-bit object ID", key)
    if not _plain(value):
        raise DocumentationError(f"{key} must be an object", key)
    entry: dict[str, Any] = {}
    if "label" in value:
        entry["label"] = _clean(value["label"], f"{key}.label", 120, key)
    if "description" in value:
        entry["description"] = _clean(value["description"], f"{key}.description", key=key)
    if "notes" in value:
        entry["notes"] = _clean(value["notes"], f"{key}.notes", key=key)
    if "status" in value:
        if value["status"] not in STATUSES:
            raise DocumentationError(f'{key}.status must be "documented", "partial" or "unknown"', key)
        entry["status"] = value["status"]
    if "documented" in value:
        documented = value["documented"]
        if not _integer(documented) or documented < 0 or documented > 100:
            raise DocumentationError(f"{key}.documented must be a whole number from 0 to 100 (a percentage)", key)
        entry["documented"] = int(documented)
    if "settings" in value:
        settings = value["settings"]
        if not _plain(settings):
            raise DocumentationError(f"{key}.settings must be an object", key)
        entry["settings"] = {}
        for index, setting in settings.items():
            if not re.match(r"^[1-8]$", index):
                raise DocumentationError(f"{key}.settings index must be 1–8", key)
            if not _plain(setting):
                raise DocumentationError(f"{key}.settings.{index} must have a label", key)
            where = f"{key}.settings.{index}"
            parsed: dict[str, Any] = {"label": _clean(setting.get("label"), f"{where}.label", 120, key)}
            for name in ("description", "values", "limits"):
                if name in setting:
                    parsed[name] = _clean(setting[name], f"{where}.{name}", key=key)
            parsed.update(_setting_input(setting, where, key))
            entry["settings"][index] = parsed
    if not entry:
        raise DocumentationError(f"{key} has no documentation", key)
    if entry.get("status") == "documented" and entry.get("documented", 100) < 100:
        raise DocumentationError(f'{key}: "documented" needs 100%, use "partial" below that', key)
    return entry


def status(entry: dict | None) -> tuple[str, int, bool]:
    """(status, percent, estimated) as the editor shows it: given by "status" and "documented", or
    estimated from the entry: half for a description, half for the eight settings by how many are named."""
    entry = entry if isinstance(entry, dict) else {}
    given, documented = entry.get("status"), entry.get("documented")
    settings = entry.get("settings")
    named = sum(1 for s in (settings if isinstance(settings, dict) else {}).values() if isinstance(s, dict) and s.get("label"))
    estimate = math.floor((50 if entry.get("description") else 0) + named / 8 * 50 + 0.5)
    if given not in STATUSES:
        given = None
    if not _integer(documented) or not 0 <= documented <= 100:
        documented = None
    if documented is not None:
        percent = documented
    elif given == "documented":
        percent = 100
    elif given == "unknown":
        percent = 0
    else:
        percent = estimate
    if given == "partial" and documented is None:
        percent = min(99, max(1, percent))
    result = given or ("documented" if percent >= 100 else "unknown" if percent <= 0 else "partial")
    return result, int(percent), given is None and documented is None


def dumps(document: dict) -> str:
    """The file as the editor writes it: two-space indentation, characters kept as they are."""
    return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def loads(text: str) -> dict:
    """Read JSON without silently dropping repeated keys or accepting NaN/Infinity."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise DocumentationError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise DocumentationError(f"Invalid JSON number: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            invalid_constant(value)
        return number

    return json.loads(text.lstrip("\ufeff"), object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float)
