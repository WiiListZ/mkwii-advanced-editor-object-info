"""Shared validator used by the desktop proposal, CLI and GitHub Actions checks."""

from dataclasses import dataclass

from . import docformat


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[str, ...]
    objects: int = 0
    settings: int = 0

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def summary(self) -> str:
        if self.errors:
            return f"Validator failed · {len(self.errors)} problem(s)"
        return f"Validator passed · {self.objects} objects · {self.settings} documented settings"


def validate_document(document) -> ValidationReport:
    try:
        # Validate the same UTF-8 JSON structure that is saved and committed.
        document = docformat.loads(docformat.dumps(document))
        parsed = docformat.parse(document)
    except (TypeError, ValueError) as error:
        errors = [str(error)]
        if isinstance(document, dict) and isinstance(document.get("objects"), dict):
            for key, value in document["objects"].items():
                try:
                    docformat.parse_entry(key, value)
                except (TypeError, ValueError) as detail:
                    if str(detail) not in errors:
                        errors.append(str(detail))
        return ValidationReport(tuple(errors))
    return ValidationReport((), len(parsed), sum(len(entry.get("settings", {})) for entry in parsed.values()))
