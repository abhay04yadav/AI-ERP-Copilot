"""Unit tests for the student resolver's three confidence bands (spec §5.5).
Scores are monkeypatched rather than relying on rapidfuzz's exact output for
a given name pair — these tests are about our threshold/outcome logic, not
about what score rapidfuzz happens to assign to "Aarav" vs "Arav"."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models.canonical import Student
from app.models.identity import MergeReviewItem
from app.models.ingestion import SourceSystem
from app.models.tenant import Tenant


def _make_tenant_and_source(session, slug: str):
    from app.core.rls import set_tenant_context

    tenant = Tenant(name=slug, slug=slug)
    session.add(tenant)
    session.flush()
    set_tenant_context(session, tenant.id)
    source = SourceSystem(tenant_id=tenant.id, name="CSV", precedence=1)
    session.add(source)
    session.flush()
    return tenant, source


def test_high_confidence_auto_links_no_review_item(app_session_factory):
    from app.services.ingestion.resolution import resolver

    session = app_session_factory()
    try:
        with session.begin():
            tenant, source = _make_tenant_and_source(session, "fuzzy-high")
            existing = Student(
                tenant_id=tenant.id, canonical_roll_no="X001", name="Aarav Sharma", dob=date(2003, 1, 15)
            )
            session.add(existing)
            session.flush()

            cleaned = {"canonical_roll_no": "X002", "name": "Aarav Sharma", "dob": "2003-01-15"}
            result = resolver.resolve_student(session, tenant.id, source.id, cleaned)

            assert result.canonical_id == existing.id
            assert result.pending_review is False
            assert session.execute(select(func.count()).select_from(MergeReviewItem)).scalar_one() == 0
    finally:
        session.close()


def test_medium_confidence_queues_review_never_auto_merges(app_session_factory, monkeypatch):
    from app.services.ingestion.resolution import resolver

    session = app_session_factory()
    try:
        with session.begin():
            tenant, source = _make_tenant_and_source(session, "fuzzy-medium")
            existing = Student(
                tenant_id=tenant.id, canonical_roll_no="X001", name="Aarav Sharma", dob=date(2003, 1, 15)
            )
            session.add(existing)
            session.flush()

            monkeypatch.setattr(resolver, "_score", lambda candidate, name, dob, email, phone: Decimal("80"))

            cleaned = {"canonical_roll_no": "X999", "name": "Totally Different Name", "dob": "2003-01-15"}
            result = resolver.resolve_student(session, tenant.id, source.id, cleaned)

            assert result.canonical_id is None
            assert result.pending_review is True

            review_items = session.execute(select(MergeReviewItem)).scalars().all()
            assert len(review_items) == 1
            assert review_items[0].candidate_canonical_id == existing.id
            assert review_items[0].status == "pending_review"
            assert session.execute(select(func.count()).select_from(Student)).scalar_one() == 1
    finally:
        session.close()


def test_low_confidence_treated_as_new_student(app_session_factory, monkeypatch):
    from app.services.ingestion.resolution import resolver

    session = app_session_factory()
    try:
        with session.begin():
            tenant, source = _make_tenant_and_source(session, "fuzzy-low")
            existing = Student(
                tenant_id=tenant.id, canonical_roll_no="X001", name="Aarav Sharma", dob=date(2003, 1, 15)
            )
            session.add(existing)
            session.flush()

            monkeypatch.setattr(resolver, "_score", lambda candidate, name, dob, email, phone: Decimal("10"))

            cleaned = {"canonical_roll_no": "X777", "name": "Nobody Similar", "dob": "1999-09-09"}
            result = resolver.resolve_student(session, tenant.id, source.id, cleaned)

            assert result.canonical_id is None
            assert result.is_new is True
            assert result.pending_review is False
    finally:
        session.close()
