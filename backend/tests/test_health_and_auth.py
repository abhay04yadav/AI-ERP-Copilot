import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(migrated_db):
    """Imports the app only after migrated_db has set DATABASE_URL etc. in the
    environment, since app.core.config.Settings() is read once at import time."""
    import app.core.config as config_module

    importlib.reload(config_module)
    import app.main as main_module

    importlib.reload(main_module)
    return TestClient(main_module.app)


def test_health_liveness(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_db_roundtrip(client):
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_register_issues_jwt_and_login_works(client):
    register_resp = client.post(
        "/auth/register",
        json={
            "tenant_name": "Test College",
            "tenant_slug": "test-college",
            "admin_email": "admin@test-college.edu",
            "admin_password": "supersecret1",
        },
    )
    assert register_resp.status_code == 200
    body = register_resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"

    login_resp = client.post(
        "/auth/login",
        json={
            "tenant_slug": "test-college",
            "email": "admin@test-college.edu",
            "password": "supersecret1",
        },
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["access_token"]


def test_login_wrong_password_is_rejected(client):
    client.post(
        "/auth/register",
        json={
            "tenant_name": "Other College",
            "tenant_slug": "other-college",
            "admin_email": "admin@other-college.edu",
            "admin_password": "supersecret1",
        },
    )
    response = client.post(
        "/auth/login",
        json={
            "tenant_slug": "other-college",
            "email": "admin@other-college.edu",
            "password": "wrong-password",
        },
    )
    assert response.status_code == 401


def test_duplicate_tenant_slug_is_rejected(client):
    payload = {
        "tenant_name": "Dup College",
        "tenant_slug": "dup-college",
        "admin_email": "admin@dup-college.edu",
        "admin_password": "supersecret1",
    }
    first = client.post("/auth/register", json=payload)
    assert first.status_code == 200
    second = client.post("/auth/register", json={**payload, "admin_email": "other@dup-college.edu"})
    assert second.status_code == 409
