from rapidfuzz import fuzz, process

# The canonical field set a ColumnMapping must (eventually) cover for each
# entity_type. Student-referencing entity types use "roll_no" / "course_code"
# — human-readable identifiers resolved against canonical tables in the
# resolution/loading stages, not the canonical students.id / courses.id
# themselves (those don't exist yet in a source file).
ENTITY_CANONICAL_FIELDS: dict[str, list[str]] = {
    "student": [
        "canonical_roll_no",
        "name",
        "dob",
        "gender",
        "category",
        "email",
        "phone",
        "admission_year",
        "programme_code",
        "status",
    ],
    "department": ["code", "name"],
    "programme": ["code", "name", "department_code"],
    "course": ["code", "name", "programme_code"],
    "enrollment": ["roll_no", "course_code", "academic_year", "status"],
    "attendance": ["roll_no", "course_code", "class_date", "session_no", "status"],
    "internal_mark": ["roll_no", "course_code", "assessment_type", "attempt", "max_marks", "obtained"],
    "fee": ["roll_no", "term", "fee_head", "amount_due", "amount_paid", "due_date", "paid_date", "status"],
}


def apply_mapping(raw_payload: dict, mapping: dict[str, str]) -> dict:
    """mapping: {canonical_field: source_header} (spec §5.3). Unmapped/extra
    source columns are simply not carried forward here — they stay available
    in raw_payload (never discarded), they just don't flow into staging."""
    return {canonical_field: raw_payload.get(source_header) for canonical_field, source_header in mapping.items()}


def suggest_mapping(source_headers: list[str], entity_type: str, score_cutoff: int = 60) -> dict[str, str | None]:
    """Fuzzy header -> canonical-field suggestion for the user to confirm
    before it's saved as a ColumnMapping (spec §5.3) — never auto-applied."""
    canonical_fields = ENTITY_CANONICAL_FIELDS.get(entity_type, [])
    available = list(source_headers)
    suggestions: dict[str, str | None] = {}

    for canonical_field in canonical_fields:
        if not available:
            suggestions[canonical_field] = None
            continue
        match = process.extractOne(
            canonical_field.replace("_", " "),
            available,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=score_cutoff,
        )
        if match is None:
            suggestions[canonical_field] = None
            continue
        matched_header = match[0]
        suggestions[canonical_field] = matched_header
        available.remove(matched_header)  # don't suggest the same header twice

    return suggestions
