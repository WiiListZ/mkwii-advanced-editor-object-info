"""Three-way merging: apply a contributor's edits without reverting other contributions."""

from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass

from . import docformat

MISSING = object()


@dataclass
class Conflict:
    path: tuple[str, ...]
    base: object
    local: object
    remote: object

    @property
    def name(self) -> str:
        return ".".join(self.path)


def merge(base: dict, local: dict, remote: dict) -> tuple[dict, list[Conflict]]:
    """Merge independent fields, retaining the local value for unresolved conflicts."""
    conflicts = []

    def clone(value):
        return MISSING if value is MISSING else copy.deepcopy(value)

    def visit(before, mine, theirs, path):
        if mine == before:
            return clone(theirs)
        if theirs == before or mine == theirs:
            return clone(mine)
        if all(isinstance(value, dict) for value in (before, mine, theirs)):
            result = {}
            for key in dict.fromkeys([*theirs, *mine, *before]):
                value = visit(before.get(key, MISSING), mine.get(key, MISSING), theirs.get(key, MISSING), (*path, key))
                if value is not MISSING:
                    result[key] = value
            return result
        conflicts.append(Conflict(path, clone(before), clone(mine), clone(theirs)))
        return clone(mine)

    return visit(base, local, remote, ()), conflicts


def resolve(document: dict, conflict: Conflict, use_local: bool):
    target = document
    for key in conflict.path[:-1]:
        target = target[key]
    value = conflict.local if use_local else conflict.remote
    if value is MISSING:
        target.pop(conflict.path[-1], None)
    else:
        target[conflict.path[-1]] = copy.deepcopy(value)


def changes(before: dict, after: dict) -> dict[str, list[str]]:
    old, new = before.get("objects", {}), after.get("objects", {})
    return {
        "changed": [key for key in new if key in old and new[key] != old[key]],
        "added": [key for key in new if key not in old],
        "removed": [key for key in old if key not in new],
    }


def diff(before: dict, after: dict) -> str:
    return "".join(difflib.unified_diff(docformat.dumps(before).splitlines(True), docformat.dumps(after).splitlines(True),
                                        fromfile="GitHub/data/objects.json", tofile="proposed/data/objects.json"))
