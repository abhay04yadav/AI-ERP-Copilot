from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin


class Tenant(PKMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(nullable=False)
    slug: Mapped[str] = mapped_column(nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"), nullable=False)
