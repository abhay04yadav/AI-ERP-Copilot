from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    """Transactional session with no tenant context pre-set. Use for routes that
    resolve their own tenant (auth) or that touch no tenant-scoped tables
    (health checks). Commits on success, rolls back on exception."""
    session = SessionLocal()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
