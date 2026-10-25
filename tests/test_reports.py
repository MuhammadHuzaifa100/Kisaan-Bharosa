"""Fraud complaint access rules.

A complaint names a dealer, so who may read the register matters as much as who may
move a case along.
"""

from app.config import settings

PAYLOAD = {
    "dealer_name": "Ittihad Agro Services",
    "dealer_location": "Grain Market, Vehari",
    "product_name": "Sona Urea 50kg",
    "suspected_batch": "LOT-FAKE-9921",
    "price_charged_pkr": 5400,
    "evidence_notes": "Refused to provide official receipt, bag stitching had no holographic security ribbon.",
}


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _file(client, token=None):
    response = client.post("/api/reports/", json=PAYLOAD, headers=_bearer(token) if token else {})
    assert response.status_code == 201, response.text
    return response.json()


def _sign_up(client, email):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Test Grower"},
    ).json()["access_token"]


def test_file_fraud_report(client, farmer_token):
    data = _file(client, farmer_token)
    assert data["report_ref"].startswith("FRD-")
    assert data["status"] == "PENDING_REVIEW"
    assert data["dealer_name"] == "Ittihad Agro Services"


def test_report_register_requires_sign_in(client, farmer_token):
    _file(client, farmer_token)
    assert client.get("/api/reports/").status_code == 401


def test_grower_sees_own_filings_only(client, farmer_token):
    report = _file(client, farmer_token)
    other = _sign_up(client, "quiet_neighbour@gmail.com")

    assert [r["id"] for r in client.get("/api/reports/", headers=_bearer(other)).json()] == []
    mine = client.get("/api/reports/", headers=_bearer(farmer_token)).json()
    assert [r["id"] for r in mine] == [report["id"]]


def test_inspector_sees_the_whole_queue(client, farmer_token, inspector_token):
    report = _file(client, farmer_token)
    listed = client.get("/api/reports/", headers=_bearer(inspector_token)).json()
    assert report["id"] in [r["id"] for r in listed]


def test_inspector_update_report_status(client, farmer_token, inspector_token):
    report = _file(client, farmer_token)
    response = client.patch(
        f"/api/reports/{report['id']}/status",
        json={"status": "INVESTIGATION_OPENED"},
        headers=_bearer(inspector_token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "INVESTIGATION_OPENED"


def test_farmer_cannot_update_report_status(client, farmer_token):
    report = _file(client, farmer_token)
    response = client.patch(
        f"/api/reports/{report['id']}/status",
        json={"status": "RESOLVED"},
        headers=_bearer(farmer_token),
    )
    assert response.status_code == 403
    assert "restricted" in response.json()["detail"].lower()


def test_invalid_status_is_rejected(client, farmer_token, inspector_token):
    report = _file(client, farmer_token)
    response = client.patch(
        f"/api/reports/{report['id']}/status",
        json={"status": "CLOSED_BY_INTEREST"},
        headers=_bearer(inspector_token),
    )
    assert response.status_code == 400


def test_anonymous_filing_is_allowed_but_throttled(client, monkeypatch):
    """Anyone can report a dealer, so the register needs a cap on how fast one
    client can fill it."""
    monkeypatch.setattr(settings, "COMPLAINT_RATE_LIMIT_REQUESTS", 2)

    assert client.post("/api/reports/", json=PAYLOAD).status_code == 201
    assert client.post("/api/reports/", json=PAYLOAD).status_code == 201

    response = client.post("/api/reports/", json=PAYLOAD)
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["code"] == "RATE_LIMITED"
    assert detail["retryable"] is True
    assert int(response.headers["Retry-After"]) >= 1
