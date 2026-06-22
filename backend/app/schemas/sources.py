from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceSystemCreate(BaseModel):
    name: str = Field(min_length=1)
    precedence: int
    """Lower wins a conflict (spec §5.7)."""


class SourceSystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    precedence: int
