"""Pure functions, one per field type (spec §5.4). Each takes a raw cell
value (str/int/float/None as read from CSV/Excel) and returns a normalized
value or None — never raises on bad input, since a normalizer's job is to
produce its best-effort value and let validators.py decide if that's usable."""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

_NULLISH = {"", "n/a", "na", "-", "null", "none", "nil"}

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%m/%d/%Y")

_GENDER_MAP = {
    "m": "male",
    "male": "male",
    "f": "female",
    "female": "female",
    "o": "other",
    "other": "other",
}

_CATEGORY_MAP = {
    "general": "GENERAL",
    "gen": "GENERAL",
    "sc": "SC",
    "st": "ST",
    "obc": "OBC",
    "ews": "EWS",
}

EXCEL_EPOCH = datetime(1899, 12, 30)  # matches Excel's serial-date epoch/leap-year quirk


def normalize_nullish(value: object) -> object | None:
    """Empty/"N/A"/"-"/"NULL" -> real None (spec §5.4)."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in _NULLISH:
        return None
    return value


def normalize_date(value: object) -> str | None:
    """Returns an ISO 'YYYY-MM-DD' string, handling dd/mm/yyyy, dd-mm-yy, and
    Excel serial dates (spec §5.4), or None if unparseable."""
    value = normalize_nullish(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int | float):
        try:
            return (EXCEL_EPOCH + timedelta(days=float(value))).date().isoformat()
        except (OverflowError, ValueError):
            return None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_roll_no(value: object) -> str | None:
    """Trimmed/upper/whitespace-collapsed canonical roll number form."""
    value = normalize_nullish(value)
    if value is None:
        return None
    collapsed = re.sub(r"\s+", "", str(value))
    return collapsed.upper() or None


def normalize_name(value: object) -> str | None:
    """Trimmed, whitespace-collapsed, title-cased for storage."""
    value = normalize_nullish(value)
    if value is None:
        return None
    collapsed = re.sub(r"\s+", " ", str(value).strip())
    return collapsed.title() or None


def normalize_phone(value: object, default_country_code: str = "91") -> str | None:
    """Digits only, with a default country code prefix applied to bare
    10-digit local numbers (spec §5.4)."""
    value = normalize_nullish(value)
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    if len(digits) == 10:
        return default_country_code + digits
    return digits


def normalize_gender(value: object) -> str | None:
    """Controlled vocabulary: male/female/other, or None if unrecognized."""
    value = normalize_nullish(value)
    if value is None:
        return None
    return _GENDER_MAP.get(str(value).strip().lower())


def normalize_category(value: object) -> str | None:
    """Controlled vocabulary for reservation category; unrecognized values
    pass through upper-cased rather than being dropped, since the category
    list varies by state/institution and we'd rather quarantine downstream
    on an unexpected value than silently lose it."""
    value = normalize_nullish(value)
    if value is None:
        return None
    text = str(value).strip()
    return _CATEGORY_MAP.get(text.lower(), text.upper())


def normalize_number(value: object) -> Decimal | None:
    """Strips %, commas; returns a Decimal or None (spec §5.4)."""
    value = normalize_nullish(value)
    if value is None:
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "").replace("%", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def normalize_int(value: object) -> int | None:
    number = normalize_number(value)
    if number is None:
        return None
    try:
        return int(number)
    except (ValueError, OverflowError):
        return None


def normalize_label(value: object) -> str | None:
    """Trim/whitespace-collapse only, no case change — department/programme/
    course names are often intentionally-cased acronyms (e.g. "CSE")."""
    value = normalize_nullish(value)
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value).strip()) or None


def normalize_email(value: object) -> str | None:
    value = normalize_nullish(value)
    if value is None:
        return None
    return str(value).strip().lower() or None


def normalize_status(value: object) -> str | None:
    value = normalize_nullish(value)
    if value is None:
        return None
    return str(value).strip().lower() or None


# code-like identifiers (department/programme/course code, roll_no) share the
# same transform: trim/collapse/upper.
normalize_code = normalize_roll_no

# entity_type -> {field_name: normalizer}. Fields not listed pass through
# normalize_nullish only (still turns "N/A"/"-" etc. into real None).
FIELD_NORMALIZERS: dict[str, dict[str, callable]] = {
    "student": {
        "canonical_roll_no": normalize_roll_no,
        "name": normalize_name,
        "dob": normalize_date,
        "gender": normalize_gender,
        "category": normalize_category,
        "email": normalize_email,
        "phone": normalize_phone,
        "admission_year": normalize_int,
        "programme_code": normalize_code,
        "status": normalize_status,
    },
    "department": {"code": normalize_code, "name": normalize_label},
    "programme": {"code": normalize_code, "name": normalize_label, "department_code": normalize_code},
    "course": {"code": normalize_code, "name": normalize_label, "programme_code": normalize_code},
    "enrollment": {
        "roll_no": normalize_roll_no,
        "course_code": normalize_code,
        "academic_year": normalize_label,
        "status": normalize_status,
    },
    "attendance": {
        "roll_no": normalize_roll_no,
        "course_code": normalize_code,
        "class_date": normalize_date,
        "session_no": normalize_int,
        "status": normalize_status,
    },
    "internal_mark": {
        "roll_no": normalize_roll_no,
        "course_code": normalize_code,
        "assessment_type": normalize_label,
        "attempt": normalize_int,
        "max_marks": normalize_number,
        "obtained": normalize_number,
        "assessment_date": normalize_date,
    },
    "fee": {
        "roll_no": normalize_roll_no,
        "term": normalize_label,
        "fee_head": normalize_label,
        "amount_due": normalize_number,
        "amount_paid": normalize_number,
        "due_date": normalize_date,
        "paid_date": normalize_date,
        "status": normalize_status,
    },
}


def clean_payload(entity_type: str, mapped_payload: dict) -> dict:
    """Applies the right per-field normalizer for entity_type to every field
    produced by mapping.apply_mapping()."""
    field_normalizers = FIELD_NORMALIZERS.get(entity_type, {})
    return {
        field: field_normalizers.get(field, normalize_nullish)(value) for field, value in mapped_payload.items()
    }


def to_jsonable(payload: dict) -> dict:
    """Converts Decimal values (normalize_number's output, e.g.
    internal_mark's max_marks/obtained, fee's amount_due/amount_paid) to
    float so the payload can be stored in a JSONB column -- psycopg's JSON
    encoder doesn't know how to serialize Decimal.

    Applied only at the JSONB-storage boundary (pipeline.py, when
    constructing StagingRecord.cleaned_payload), never to the dict
    validators.py::validate_record sees: its range checks
    (`max_marks <= 0`, `obtained > max_marks`, ...) need Decimal/numeric
    types, not a JSON-safe copy.
    """
    return {field: float(value) if isinstance(value, Decimal) else value for field, value in payload.items()}
