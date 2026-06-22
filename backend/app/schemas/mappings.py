from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ColumnMappingCreate(BaseModel):
    source_system_id: UUID
    entity_type: str
    mapping: dict[str, str]
    """{canonical_field: source_header} (spec §5.3)."""


class ColumnMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_system_id: UUID
    entity_type: str
    mapping: dict[str, str]
    version: int


class MappingSuggestRequest(BaseModel):
    source_system_id: UUID
    entity_type: str
    headers: list[str]


class MappingSuggestResponse(BaseModel):
    suggestions: dict[str, str | None]
