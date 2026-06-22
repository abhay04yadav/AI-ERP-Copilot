import hashlib
import uuid

from sqlalchemy.orm import Session

from app.core.storage import StorageBackend
from app.models.ingestion import ImportBatch, RawFile, RawRecord
from app.services.ingestion.connectors.base import Connector


def compute_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store_raw_file(
    session: Session,
    storage: StorageBackend,
    import_batch: ImportBatch,
    content: bytes,
    original_filename: str,
    content_hash: str,
) -> RawFile:
    """Original file retained byte-for-byte (spec §5.2) for recovery/audit.

    id is pre-generated (not left to the server default) so storage.save()
    can build storage_uri/content before the row is ever inserted — raw_files
    is granted SELECT+INSERT only, no UPDATE (append-only/immutable), so a
    flush-then-mutate-then-flush pattern here would fail on the second flush.
    """
    raw_file = RawFile(
        id=uuid.uuid4(),
        tenant_id=import_batch.tenant_id,
        import_batch_id=import_batch.id,
        storage_uri="",
        original_filename=original_filename,
        content_hash=content_hash,
        byte_size=len(content),
    )
    storage.save(raw_file, content)
    session.add(raw_file)
    session.flush()
    return raw_file


def parse_raw_records(
    session: Session, import_batch: ImportBatch, connector: Connector, content: bytes
) -> int:
    """Each source row captured verbatim as JSON before any transformation
    (spec §5.2). Returns the row count."""
    row_count = 0
    for row_number, row in enumerate(connector.read_rows(content), start=1):
        session.add(
            RawRecord(
                tenant_id=import_batch.tenant_id,
                import_batch_id=import_batch.id,
                row_number=row_number,
                raw_payload=row,
            )
        )
        row_count += 1
    return row_count
