"""Pure unit tests for app/services/import_validation.py — no DB, no
async, no Celery. Mirrors the old backend's import_valid.py rules
exactly; see that module's docstring for the source-of-truth mapping."""

import pytest

from app.services.import_validation import (
    DimensionForValidation,
    ImportValidationError,
    validate_and_parse,
)


def _dims() -> list[DimensionForValidation]:
    return [
        DimensionForValidation(name="YEAR", in_file=True, column_location="1", default_value=None),
        DimensionForValidation(
            name="AMOUNT", in_file=True, column_location="2", default_value=None
        ),
    ]


def test_valid_file_parses_into_dimension_keyed_rows() -> None:
    csv_bytes = b"YEAR,AMOUNT\r\n2024,100\r\n2025,200\r\n"
    rows = validate_and_parse(csv_bytes, delimiter=",", has_header=True, dimensions=_dims())
    assert rows == [{"YEAR": "2024", "AMOUNT": "100"}, {"YEAR": "2025", "AMOUNT": "200"}]


def test_no_dimensions_configured_is_rejected() -> None:
    with pytest.raises(ImportValidationError, match="no dimensions configured"):
        validate_and_parse(b"a,b\r\n1,2\r\n", delimiter=",", has_header=True, dimensions=[])


def test_file_with_only_a_header_is_rejected() -> None:
    with pytest.raises(ImportValidationError, match="at least one data row"):
        validate_and_parse(b"YEAR,AMOUNT\r\n", delimiter=",", has_header=True, dimensions=_dims())


def test_delimiter_not_in_header_is_rejected() -> None:
    with pytest.raises(ImportValidationError, match="delimiter"):
        validate_and_parse(
            b"YEAR;AMOUNT\r\n2024;100\r\n", delimiter=",", has_header=True, dimensions=_dims()
        )


def test_wrong_column_count_is_rejected() -> None:
    with pytest.raises(ImportValidationError, match="Expected 2 column"):
        validate_and_parse(
            b"YEAR,AMOUNT,EXTRA\r\n2024,100,x\r\n",
            delimiter=",",
            has_header=True,
            dimensions=_dims(),
        )


def test_blank_cell_with_no_default_is_rejected_with_row_and_column() -> None:
    with pytest.raises(ImportValidationError, match="Row 3, column 2"):
        validate_and_parse(
            b"YEAR,AMOUNT\r\n2024,100\r\n2025,\r\n",
            delimiter=",",
            has_header=True,
            dimensions=_dims(),
        )


def test_blank_cell_falls_back_to_configured_default() -> None:
    dims = [
        DimensionForValidation(name="YEAR", in_file=True, column_location="1", default_value=None),
        DimensionForValidation(name="AMOUNT", in_file=True, column_location="2", default_value="0"),
    ]
    rows = validate_and_parse(
        b"YEAR,AMOUNT\r\n2024,\r\n", delimiter=",", has_header=True, dimensions=dims
    )
    assert rows == [{"YEAR": "2024", "AMOUNT": "0"}]


def test_non_in_file_dimension_gets_default_value_on_every_row() -> None:
    dims = [
        DimensionForValidation(name="YEAR", in_file=True, column_location="1", default_value=None),
        DimensionForValidation(
            name="AMOUNT", in_file=True, column_location="2", default_value=None
        ),
        DimensionForValidation(
            name="REGION", in_file=False, column_location=None, default_value="US"
        ),
    ]
    rows = validate_and_parse(
        b"YEAR,AMOUNT\r\n2024,100\r\n2025,200\r\n", delimiter=",", has_header=True, dimensions=dims
    )
    assert rows == [
        {"YEAR": "2024", "AMOUNT": "100", "REGION": "US"},
        {"YEAR": "2025", "AMOUNT": "200", "REGION": "US"},
    ]


def test_no_header_mode_validates_first_data_row_column_count() -> None:
    rows = validate_and_parse(
        b"2024,100\r\n2025,200\r\n", delimiter=",", has_header=False, dimensions=_dims()
    )
    assert rows == [{"YEAR": "2024", "AMOUNT": "100"}, {"YEAR": "2025", "AMOUNT": "200"}]
