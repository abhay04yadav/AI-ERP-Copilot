"""Per-entity validation rules (spec §5.4): required fields present, ranges
sane. Operates on an already-normalized payload (normalizers.py runs first).
Returns a list of error strings — empty means valid. Never raises and never
drops a row; the caller (pipeline.py) quarantines rows with errors instead."""

from datetime import date

REQUIRED_FIELDS: dict[str, list[str]] = {
    "student": ["canonical_roll_no", "name"],
    "department": ["code", "name"],
    "programme": ["code", "name"],
    "course": ["code", "name"],
    "enrollment": ["roll_no", "course_code", "academic_year"],
    "attendance": ["roll_no", "course_code", "class_date", "status"],
    "internal_mark": ["roll_no", "course_code", "assessment_type", "max_marks", "obtained"],
    "fee": ["roll_no", "term", "fee_head"],
}


def validate_record(entity_type: str, cleaned: dict) -> list[str]:
    errors: list[str] = [
        f"missing required field: {field}"
        for field in REQUIRED_FIELDS.get(entity_type, [])
        if cleaned.get(field) is None
    ]
    if errors:
        return errors  # don't range-check fields that aren't even present

    if entity_type == "student" and cleaned.get("dob") is not None:
        errors.extend(_validate_dob(cleaned["dob"]))

    if entity_type == "attendance" and cleaned.get("status") not in ("present", "absent", "leave"):
        errors.append(f"invalid attendance status: {cleaned.get('status')!r}")

    if entity_type == "internal_mark":
        errors.extend(_validate_marks(cleaned.get("max_marks"), cleaned.get("obtained")))

    if entity_type == "fee":
        errors.extend(_validate_non_negative("amount_due", cleaned.get("amount_due")))
        errors.extend(_validate_non_negative("amount_paid", cleaned.get("amount_paid")))

    return errors


def _validate_dob(dob_iso: str) -> list[str]:
    try:
        dob = date.fromisoformat(dob_iso)
    except ValueError:
        return [f"unparseable dob: {dob_iso!r}"]
    if dob > date.today():
        return ["dob is in the future"]
    if dob.year < 1900:
        return ["dob implausibly old"]
    return []


def _validate_marks(max_marks, obtained) -> list[str]:
    if max_marks is None or obtained is None:
        return []  # required-field check already caught this
    errors = []
    if max_marks <= 0:
        errors.append("max_marks must be positive")
    if obtained < 0:
        errors.append("obtained marks cannot be negative")
    if max_marks > 0 and obtained > max_marks:
        errors.append(f"obtained ({obtained}) exceeds max_marks ({max_marks})")
    return errors


def _validate_non_negative(field: str, value) -> list[str]:
    if value is not None and value < 0:
        return [f"{field} cannot be negative"]
    return []
