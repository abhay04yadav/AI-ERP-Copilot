import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parent.parent

_ALL_TABLES = (
    "users",
    "audit_log",
    "tenants",
    "source_systems",
    "column_mappings",
    "import_batches",
    "raw_files",
    "raw_records",
    "staging_records",
    "entity_identity_map",
    "merge_review_items",
    "data_conflicts",
    "departments",
    "programmes",
    "courses",
    "faculty",
    "students",
    "enrollment",
    "attendance",
    "internal_marks",
    "fees",
    "semester_results",
)


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16") as pg:
        yield pg


@pytest.fixture(scope="session")
def app_db_password() -> str:
    return "test-app-user-password"


@pytest.fixture(scope="session")
def migrated_db(postgres_container, app_db_password, monkeysession):
    superuser_url = postgres_container.get_connection_url().replace("psycopg2", "psycopg")
    app_url = superuser_url.replace(
        f"{postgres_container.username}:{postgres_container.password}",
        f"app_user:{app_db_password}",
    )

    monkeysession.setenv("DATABASE_URL", app_url)
    monkeysession.setenv("MIGRATIONS_DATABASE_URL", superuser_url)
    monkeysession.setenv("APP_DB_PASSWORD", app_db_password)
    monkeysession.setenv("JWT_SECRET_KEY", "test-secret")

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        check=True,
        env={**os.environ},
    )

    return {"app_url": app_url, "superuser_url": superuser_url}


@pytest.fixture(scope="session")
def monkeysession():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture()
def app_session_factory(migrated_db):
    engine = create_engine(migrated_db["app_url"])
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def superuser_connection(migrated_db):
    engine = create_engine(migrated_db["superuser_url"])
    conn = engine.connect()
    yield conn
    conn.execute(text(f"TRUNCATE {', '.join(_ALL_TABLES)} CASCADE"))
    conn.commit()
    conn.close()
    engine.dispose()


@pytest.fixture()
def client(migrated_db):
    """Imports the app only after migrated_db has set DATABASE_URL etc. in the
    environment, since app.core.config.Settings() is read once at import time."""
    import app.core.config as config_module

    importlib.reload(config_module)
    import app.main as main_module

    importlib.reload(main_module)
    return TestClient(main_module.app)
