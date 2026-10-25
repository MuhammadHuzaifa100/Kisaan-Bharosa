"""Storing a verdict that a browser drew with Puter.js.

No server key is involved on this path, so the endpoint is the only thing deciding
whether a model's claim becomes a record. These tests pin that gate: the schema, the
ownership rule, the no-overwrite rule and the label that keeps the verdict honest.
"""

import io
import uuid

import pytest
from PIL import Image

from app.config import settings
from app.services.analysis import invalidate_provider


@pytest.fixture(autouse=True)
def engine_off(monkeypatch):
    """Every record in this file is one the server engine could not analyse."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    invalidate_provider()
    yield
    invalidate_provider()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _sign_up(client, email):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Test Grower"},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def _pending_scan(client, token):
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), color=(34, 139, 34)).save(buf, format="JPEG")
    response = client.post(
        "/api/scans/analyze",
        files={"file": ("specimen.jpg", buf.getvalue(), "image/jpeg")},
        headers=_bearer(token),
    )
    assert response.status_code == 503, response.text
    return response.json()["detail"]["scan_id"]


def _report(**overrides):
    payload = {
        "classification": "Agricultural Input Package",
        "subject_name": "Sona Urea 50kg",
        "verdict": "COUNTERFEIT SUSPECTED",
        "confidence_score": 82,
        "executive_summary": "Printed lot code is smudged and the PSQCA licence is absent.",
        "properties": [
            {
                "property_name": "PSQCA Mark",
                "status": "FLAGGED",
                "observed_value": "No licence number printed on the front panel",
                "benchmark_standard": "PSQCA certification mark required on fertiliser sacks",
            },
            {
                "property_name": "Batch Code",
                "status": "FLAGGED",
                "observed_value": "Edge bleeding on the lot stamp",
                "benchmark_standard": "Offset-quality batch printing",
            },
        ],
        "regulatory_alignment": "PSQCA (Fertilisers) Rules",
        "protocol_action": "Retain the sample and escalate to the district regulator.",
        "provider_model": "gpt-5.6-luna",
        "latency_ms": 4100,
    }
    payload.update(overrides)
    return payload


def test_browser_verdict_is_stored_and_labelled_as_unverified(client, farmer_token):
    scan_id = _pending_scan(client, farmer_token)

    response = client.post(
        f"/api/scans/{scan_id}/client-analysis",
        json=_report(),
        headers=_bearer(farmer_token),
    )

    assert response.status_code == 200, response.text
    stored = response.json()
    assert stored["analysis_status"] == "COMPLETED"
    assert stored["verdict"] == "COUNTERFEIT SUSPECTED"
    assert stored["confidence_score"] == 82
    assert len(stored["properties"]) == 2
    # The provenance string has to say where the verdict actually came from.
    assert stored["analysis_model"] == "puter.js:gpt-5.6-luna"
    assert stored["verdict_source"] == "browser"

    reread = client.get(f"/api/scans/{scan_id}", headers=_bearer(farmer_token)).json()
    assert reread["verdict_source"] == "browser"


def test_anonymous_caller_cannot_store_a_verdict(client):
    token = _sign_up(client, f"anon.{uuid.uuid4().hex[:8]}@example.com")
    scan_id = _pending_scan(client, token)

    response = client.post(f"/api/scans/{scan_id}/client-analysis", json=_report())
    assert response.status_code == 401


def test_another_grower_cannot_write_into_someone_elses_record(client, farmer_token):
    scan_id = _pending_scan(client, farmer_token)
    intruder = _sign_up(client, f"snoop.{uuid.uuid4().hex[:8]}@example.com")

    response = client.post(
        f"/api/scans/{scan_id}/client-analysis", json=_report(), headers=_bearer(intruder)
    )
    # Reads as missing rather than forbidden, so record ids leak nothing.
    assert response.status_code == 404


def test_a_report_that_is_not_a_valid_audit_is_rejected(client, farmer_token):
    scan_id = _pending_scan(client, farmer_token)

    bogus = client.post(
        f"/api/scans/{scan_id}/client-analysis",
        json=_report(verdict="PROBABLY FINE"),
        headers=_bearer(farmer_token),
    )
    assert bogus.status_code == 422

    out_of_range = client.post(
        f"/api/scans/{scan_id}/client-analysis",
        json=_report(confidence_score=140),
        headers=_bearer(farmer_token),
    )
    assert out_of_range.status_code == 422

    still_pending = client.get(f"/api/scans/{scan_id}", headers=_bearer(farmer_token)).json()
    assert still_pending["analysis_status"] == "PENDING_ANALYSIS"
    assert still_pending["verdict"] is None


def test_a_report_naming_no_markers_is_refused(client, farmer_token):
    scan_id = _pending_scan(client, farmer_token)

    response = client.post(
        f"/api/scans/{scan_id}/client-analysis",
        json=_report(properties=[]),
        headers=_bearer(farmer_token),
    )
    assert response.status_code == 422
    assert "no inspected markers" in response.json()["detail"]


def test_a_record_with_a_verdict_is_not_overwritten(client, farmer_token):
    scan_id = _pending_scan(client, farmer_token)
    first = client.post(
        f"/api/scans/{scan_id}/client-analysis", json=_report(), headers=_bearer(farmer_token)
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/scans/{scan_id}/client-analysis",
        json=_report(verdict="VERIFIED AUTHENTIC"),
        headers=_bearer(farmer_token),
    )
    assert second.status_code == 409

    unchanged = client.get(f"/api/scans/{scan_id}", headers=_bearer(farmer_token)).json()
    assert unchanged["verdict"] == "COUNTERFEIT SUSPECTED"


def test_deployment_can_turn_browser_analysis_off(client, farmer_token, monkeypatch):
    monkeypatch.setattr(settings, "PUTER_AI_ENABLED", False)
    scan_id = _pending_scan(client, farmer_token)

    response = client.post(
        f"/api/scans/{scan_id}/client-analysis", json=_report(), headers=_bearer(farmer_token)
    )
    assert response.status_code == 503


def test_engine_status_advertises_the_browser_path(client):
    status = client.get("/api/scans/engine/status").json()
    assert status["configured"] is False
    assert status["browser_fallback"]["enabled"] is True
    assert status["browser_fallback"]["model"]
