from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ImportBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_system_id: UUID
    entity_type: str
    status: str
    row_count_raw: int
    row_count_loaded: int
    row_count_quarantined: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    reconciliation_report: dict | None


class QuarantineRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cleaned_payload: dict
    validation_errors: dict | None
