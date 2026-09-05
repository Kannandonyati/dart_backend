"""File-level validation and row parsing for Run Import.

Ported faithfully from the old backend's `run_import/functions/
import_valid.py` — unlike most of what this rebuild has replaced,
this validation logic is genuinely well-designed (plain, readable
Python, not hidden behind `sp_master`), so it's kept, not redesigned:

- the file needs a header plus at least one data row (when the app is
  configured with a header)
- the configured delimiter must actually appear in the header line
- every dimension configured for this recon+app must exist before an
  import can run at all — Dimension Linking (Phase 4) is a hard
  prerequisite, not optional
- the header's column count must exactly match the highest configured
  `column_location`
- for every `in_file` dimension, a blank cell is only acceptable if
  that dimension also has a configured `default_value` fallback — same
  rule the old backend enforced, now expressible directly through
  Phase 4's schema (a mapping can carry both `column_location` and
  `default_value` at once, exactly for this case)
- validation is whole-file, before any write: the first violation
  aborts the entire import, matching Phase 4's own CSV-import behavior
  (see dimensions.py's `import_dimensions`)

Deliberately framework-agnostic (no DB session, no FastAPI, no Celery)
so it can be unit-tested directly and reused from both the upload
endpoint's parsing decision and the Celery task's actual execution.
"""

import csv
import io
from dataclasses import dataclass


class ImportValidationError(Exception):
    pass


@dataclass
class DimensionForValidation:
    name: str
    in_file: bool
    column_location: str | None
    default_value: str | None


def validate_and_parse(
    raw: bytes,
    *,
    delimiter: str,
    has_header: bool,
    dimensions: list[DimensionForValidation],
) -> list[dict[str, str]]:
    if not dimensions:
        raise ImportValidationError(
            "This recon has no dimensions configured for this app — "
            "complete Dimension Linking before importing."
        )

    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    min_lines = 2 if has_header else 1
    if len(lines) < min_lines:
        raise ImportValidationError(
            f"The file must contain {'a header row and ' if has_header else ''}"
            "at least one data row."
        )

    if has_header and delimiter not in lines[0]:
        raise ImportValidationError(
            f'The configured delimiter "{delimiter}" was not found in the header row.'
        )

    in_file_dims = [d for d in dimensions if d.in_file]
    default_only_dims = [d for d in dimensions if not d.in_file]

    resolved: list[tuple[DimensionForValidation, int]] = []
    for dim in in_file_dims:
        try:
            column_index = int(dim.column_location or "")
        except ValueError as exc:
            raise ImportValidationError(
                f'Dimension "{dim.name}" has an invalid file column configured.'
            ) from exc
        if column_index < 1:
            raise ImportValidationError(
                f'Dimension "{dim.name}" has an invalid file column configured.'
            )
        resolved.append((dim, column_index))

    expected_columns = max((idx for _, idx in resolved), default=0)

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    all_rows = list(reader)
    data_rows = all_rows[1:] if has_header else all_rows

    if expected_columns:
        check_row: list[str] = all_rows[0] if has_header else (data_rows[0] if data_rows else [])
        if len(check_row) != expected_columns:
            raise ImportValidationError(
                f"Expected {expected_columns} column(s) based on the configured "
                f"dimensions, found {len(check_row)}."
            )

    parsed_rows: list[dict[str, str]] = []
    first_data_line = 2 if has_header else 1
    for offset, row in enumerate(data_rows):
        line_no = first_data_line + offset
        record: dict[str, str] = {}
        for dim, column_index in resolved:
            cell = row[column_index - 1].strip() if column_index - 1 < len(row) else ""
            if not cell:
                if not dim.default_value:
                    raise ImportValidationError(
                        f'Row {line_no}, column {column_index}: "{dim.name}" is blank '
                        "and has no default value configured."
                    )
                cell = dim.default_value
            record[dim.name] = cell
        for dim in default_only_dims:
            record[dim.name] = dim.default_value or ""
        parsed_rows.append(record)

    return parsed_rows
