"""The shared title/body standard for documentation pull requests."""

from dataclasses import dataclass

from . import DATA_PATH
from .merge import changes
from .validation import validate_document


@dataclass(frozen=True)
class Proposal:
    title: str
    body: str


def format_proposal(before: dict, after: dict, evidence: str = "", base_commit: str = "",
                    reviewed: bool = False, game_tested: bool = False) -> Proposal:
    report = validate_document(after)
    if not report.valid:
        raise ValueError("\n".join(report.errors))
    delta = changes(before, after)
    names = [name for group in delta.values() for name in sorted(group)]
    if not names:
        raise ValueError("There are no changes to propose.")
    title = "docs(objects): " + ", ".join(name[:60] for name in names[:3])
    if len(names) > 3:
        title += f" (+{len(names) - 3} more)"
    lines = ["## Summary", "", f"Update object documentation in `{DATA_PATH}`.", "", "## Objects changed", ""]
    for kind, group in delta.items():
        if not group:
            continue
        lines += [f"### {kind.capitalize()} ({len(group)})", ""]
        lines += [f"- `{key[:100]}`" for key in sorted(group)[:50]]
        if len(group) > 50:
            lines.append(f"- …and {len(group) - 50} more; see the file diff.")
        lines.append("")
    lines += ["## Evidence", "", evidence.strip()[:10000] or "No additional evidence supplied; behaviour requires maintainer review.", "",
              "## Validation", "", "- [x] The proposed JSON passes the MKWii object documentation validator.",
              "- [x] Only `data/objects.json` is included in the contribution commit.",
              f"- [{'x' if reviewed else ' '}] The contributor reviewed the JSON diff and documentation coverage.",
              f"- [{'x' if game_tested else ' '}] The contributor verified the documented behaviour in the game."]
    if base_commit:
        lines += ["", "## Base revision", "", f"`{base_commit}`"]
    return Proposal(title, "\n".join(lines) + "\n")
