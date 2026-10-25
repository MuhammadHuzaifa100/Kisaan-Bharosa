import pytest

from app.config import settings
from app.models.user import User
from app.services.auth_service import ensure_bootstrap_inspector


def test_register_new_user(client):
    payload = {
        "email": "new_grower@kisaan.pk",
        "password": "StrongPassword123!",
        "full_name": "Muhammad Aslam",
        "role": "farmer",
        "organization": "Aslam Citrus Orchards",
        "district": "Sargodha",
    }
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "new_grower@kisaan.pk"
    assert data["user"]["role"] == "farmer"

def test_register_duplicate_email(client):
    payload = {
        "email": "new_grower@kisaan.pk",
        "password": "AnotherPassword123!",
        "full_name": "Duplicate User",
    }
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]

def test_login_success(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "new_grower@kisaan.pk", "password": "StrongPassword123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["full_name"] == "Muhammad Aslam"

def test_login_invalid_password(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "new_grower@kisaan.pk", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert "Invalid email address or password" in response.json()["detail"]

def test_get_current_user_profile(client, farmer_token):
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {farmer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test_farmer@kisaan.pk"
    assert data["role"] == "farmer"

def test_get_profile_unauthorized(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_registration_cannot_grant_a_staff_role(client):
    """The role used to come from the request body, so anyone could sign up as an inspector."""
    response = client.post(
        "/api/auth/register",
        json={
            "email": "wannable@kisaan.pk",
            "password": "StrongPassword123!",
            "full_name": "Wannable Inspector",
            "role": "inspector",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]

    profile = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert profile["role"] == "farmer"

    filing = client.post(
        "/api/reports/",
        json={
            "dealer_name": "Someone Else",
            "dealer_location": "Some Market",
            "product_name": "Sona Urea",
            "evidence_notes": "Bag seal carried no hologram and no receipt was issued.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert filing.status_code == 201, filing.text
    report = filing.json()
    patch = client.patch(
        f"/api/reports/{report['id']}/status",
        json={"status": "RESOLVED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch.status_code == 403


def test_registration_rejects_a_weak_password(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "weak@kisaan.pk", "password": "1234567", "full_name": "Weak Pass"},
    )
    assert response.status_code == 422


def test_bootstrap_creates_the_configured_inspector(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "BOOTSTRAP_INSPECTOR_EMAIL", "chief.inspector@kisaan.pk")
    monkeypatch.setattr(settings, "BOOTSTRAP_INSPECTOR_PASSWORD", "long-enough-staff-pass")
    ensure_bootstrap_inspector(db_session)

    staff = db_session.query(User).filter(User.email == "chief.inspector@kisaan.pk").one()
    assert staff.role == "inspector"
    assert client.post(
        "/api/auth/login",
        json={"email": "chief.inspector@kisaan.pk", "password": "long-enough-staff-pass"},
    ).status_code == 200


def test_bootstrap_never_takes_over_an_existing_account(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "BOOTSTRAP_INSPECTOR_EMAIL", "test_farmer@kisaan.pk")
    monkeypatch.setattr(settings, "BOOTSTRAP_INSPECTOR_PASSWORD", "long-enough-staff-pass")
    ensure_bootstrap_inspector(db_session)

    grower = db_session.query(User).filter(User.email == "test_farmer@kisaan.pk").one()
    assert grower.role == "farmer"


def test_bootstrap_requires_a_strong_staff_password(client, db_session, monkeypatch):

    monkeypatch.setattr(settings, "BOOTSTRAP_INSPECTOR_EMAIL", "short@kisaan.pk")
    monkeypatch.setattr(settings, "BOOTSTRAP_INSPECTOR_PASSWORD", "too-short")
    with pytest.raises(RuntimeError, match="12 characters"):
        ensure_bootstrap_inspector(db_session)
