"""Pure-function unit tests for cleaning/normalizers.py (spec §5.4) — no DB,
no fixtures needed."""

from decimal import Decimal

from app.services.ingestion.cleaning.normalizers import (
    clean_payload,
    normalize_category,
    normalize_date,
    normalize_gender,
    normalize_int,
    normalize_name,
    normalize_nullish,
    normalize_number,
    normalize_phone,
    normalize_roll_no,
)


def test_normalize_nullish_variants_become_none():
    for value in ("", "N/A", "n/a", "-", "NULL", "null", "  ", None):
        assert normalize_nullish(value) is None


def test_normalize_nullish_passes_through_real_values():
    assert normalize_nullish("CS101") == "CS101"
    assert normalize_nullish(42) == 42


def test_normalize_date_handles_multiple_formats():
    assert normalize_date("2003-05-12") == "2003-05-12"
    assert normalize_date("12/05/2003") == "2003-05-12"
    assert normalize_date("12-05-2003") == "2003-05-12"


def test_normalize_date_handles_excel_serial():
    # Excel serial 37753 == 2003-05-12 (epoch 1899-12-30 + 37753 days)
    assert normalize_date(37753) == "2003-05-12"


def test_normalize_date_unparseable_returns_none():
    assert normalize_date("not a date") is None
    assert normalize_date("") is None


def test_normalize_roll_no_trims_and_uppercases():
    assert normalize_roll_no("  cs101 ") == "CS101"
    assert normalize_roll_no("cs 101") == "CS101"
    assert normalize_roll_no(None) is None


def test_normalize_name_collapses_whitespace_and_title_cases():
    assert normalize_name("  john   doe ") == "John Doe"
    assert normalize_name(None) is None


def test_normalize_phone_adds_default_country_code_to_10_digits():
    assert normalize_phone("9876543210") == "919876543210"
    assert normalize_phone("+91 98765 43210") == "919876543210"
    assert normalize_phone("") is None


def test_normalize_gender_controlled_vocabulary():
    assert normalize_gender("M") == "male"
    assert normalize_gender("female") == "female"
    assert normalize_gender("x") is None  # unrecognized -> None, not invented


def test_normalize_category_passes_unrecognized_through_uppercased():
    assert normalize_category("sc") == "SC"
    assert normalize_category("some_other_state_category") == "SOME_OTHER_STATE_CATEGORY"


def test_normalize_number_strips_percent_and_commas():
    assert normalize_number("1,234") == Decimal("1234")
    assert normalize_number("85%") == Decimal("85")
    assert normalize_number("not a number") is None


def test_normalize_int_truncates_decimal():
    assert normalize_int("42.7") == 42
    assert normalize_int(None) is None


def test_clean_payload_applies_per_field_normalizer_for_entity_type():
    mapped = {"canonical_roll_no": " cs101 ", "name": "  jane   doe ", "dob": "12/05/2003", "gender": "F"}
    cleaned = clean_payload("student", mapped)
    assert cleaned == {
        "canonical_roll_no": "CS101",
        "name": "Jane Doe",
        "dob": "2003-05-12",
        "gender": "female",
    }


def test_clean_payload_unknown_field_falls_back_to_nullish_normalization():
    cleaned = clean_payload("student", {"some_unmapped_field": "N/A"})
    assert cleaned == {"some_unmapped_field": None}
