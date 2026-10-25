"""Analysis pipeline tests.

The provider is faked at its boundary, so these assert the contract: whatever the
engine answers is stored verbatim, and whatever it cannot answer never becomes a
fabricated verdict.
"""

import io
import json

import pytest
from PIL import Image

from app.config import settings
from app.schemas.scan import DiagnosticReport, TechnicalProperty
from app.services.analysis import invalidate_provider
from app.services.analysis.errors import (
    AnalysisBadOutput,
    AnalysisNotConfigured,
    AnalysisRateLimited,
    AnalysisTimeout,
    InvalidCredentials,
    ModelUnavailable,
)
from app.services.analysis.provider import AnalysisOutcome
from app.models.scan import ScanRecord

MEDIA = "image/jpeg"


def _report(subject="Sona Urea (Prilled)", verdict="COUNTERFEIT SUSPECTED", confidence=41):
    return DiagnosticReport(
        classification="Agricultural Input Package",
        subject_name=subject,
        verdict=verdict,
        confidence_score=confidence,
        executive_summary="Printed MRP exceeds the notified ceiling and the seal is misaligned.",
        properties=[
            TechnicalProperty(
                property_name="Printed MRP",
                status="FLAGGED",
                observed_value="PKR 6,900 per 50 kg bag",
                benchmark_standard="Notified ceiling PKR 4,650 per 50 kg bag",
            )
        ],
        regulatory_alignment="Contradicts the current GOP notified price order.",
        protocol_action="Retain the bag and file a non-compliance report.",
    )


def _outcome(report, model="gemini-3.8-flash", latency=1234):
    return AnalysisOutcome(report=report, model_used=model, grounding_used=True, latency_ms=latency)


@pytest.fixture
def configured_key(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-not-secret")
    invalidate_provider()
    yield
    invalidate_provider()


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    invalidate_provider()
    yield
    invalidate_provider()


@pytest.fixture
def fake_provider(monkeypatch):
    """Patch GeminiProvider.analyze and record how it was called."""
    calls = []

    def install(impl):
        def _analyze(self, image, media_type):
            calls.append({"size": image.size, "media_type": media_type})
            return impl(image, media_type)

        monkeypatch.setattr(
            "app.services.analysis.provider.GeminiProvider.analyze", _analyze, raising=True
        )
        return calls

    return install


def _upload(client, color=(200, 30, 30), filename="specimen.jpg", mime=MEDIA, token=None):
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), color=color).save(buf, format="JPEG")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        "/api/scans/analyze",
        files={"file": (filename, buf.getvalue(), mime)},
        headers=headers,
    )

def test_engine_status_reports_unconfigured(no_key, client):
    body = client.get("/api/scans/engine/status").json()
    assert body["configured"] is False
    assert body["engine"] is None


def test_unconfigured_engine_never_fabricates_a_verdict(no_key, client, db_session):
    response = _upload(client)
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "ANALYSIS_UNAVAILABLE"
    assert detail["analysis_status"] == "PENDING_ANALYSIS"

    record = db_session.query(ScanRecord).filter(ScanRecord.id == detail["scan_id"]).one()
    assert record.verdict is None
    assert record.executive_summary is None
    assert record.properties_json is None
    assert record.image_filename  # photograph kept so it can be audited later


def test_provider_answer_is_stored_verbatim(configured_key, client, fake_provider, db_session):
    calls = fake_provider(lambda image, media: _outcome(_report(subject="Engro Urea (Granular)")))
    response = _upload(client, color=(10, 90, 200))
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["analysis_status"] == "COMPLETED"
    assert body["subject_name"] == "Engro Urea (Granular)"
    assert body["verdict"] == "COUNTERFEIT SUSPECTED"
    assert body["confidence_score"] == 41
    assert body["analysis_model"] == "gemini-3.8-flash"
    assert body["verdict_source"] == "server"
    assert body["analysis_latency_ms"] == 1234
    assert body["properties"][0]["observed_value"] == "PKR 6,900 per 50 kg bag"

    # The bytes actually uploaded are the bytes handed to the engine.
    assert calls[0]["media_type"] == MEDIA
    assert calls[0]["size"] == (320, 240)

    record = db_session.query(ScanRecord).filter(ScanRecord.id == body["id"]).one()
    assert json.loads(record.properties_json)[0]["status"] == "FLAGGED"


def test_inconclusive_answer_is_not_upgraded_to_authentic(configured_key, client, fake_provider):
    fake_provider(
        lambda image, media: _outcome(
            DiagnosticReport(
                classification="Unidentified Sample",
                subject_name="Unidentified",
                verdict="INCONCLUSIVE",
                confidence_score=12,
                executive_summary="Photograph is too out of focus to read the printed batch code.",
                properties=[
                    TechnicalProperty(
                        property_name="Batch Code Legibility",
                        status="INCONCLUSIVE",
                        observed_value="Not legible",
                        benchmark_standard="Legible inkjet batch code",
                    )
                ],
                regulatory_alignment="No determination made.",
                protocol_action="Re-photograph the printed face of the bag in daylight.",
            )
        )
    )
    body = _upload(client).json()
    assert body["classification"] == "Unidentified Sample"
    assert body["verdict"] == "INCONCLUSIVE"
    assert body["properties"][0]["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "exc,expected_status,expected_code",
    [
        (InvalidCredentials("rejected"), 503, "ANALYSIS_AUTH_FAILED"),
        (ModelUnavailable("no model"), 503, "ANALYSIS_MODEL_UNAVAILABLE"),
        (AnalysisRateLimited("quota"), 503, "ANALYSIS_RATE_LIMITED"),
        (AnalysisTimeout("slow"), 504, "ANALYSIS_TIMEOUT"),
        (AnalysisBadOutput("garbage"), 502, "ANALYSIS_BAD_RESPONSE"),
    ],
)
def test_provider_failures_map_to_honest_status(
    configured_key, client, fake_provider, db_session, exc, expected_status, expected_code
):
    def raise_it(image, media):
        raise exc

    fake_provider(raise_it)
    response = _upload(client)
    assert response.status_code == expected_status
    detail = response.json()["detail"]
    assert detail["code"] == expected_code
    assert detail["analysis_status"] == "FAILED"

    record = db_session.query(ScanRecord).filter(ScanRecord.id == detail["scan_id"]).one()
    assert record.verdict is None
    assert record.analysis_error == exc.message


def _sign_up(client, email):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Case Owner"},
    ).json()["access_token"]


def test_reanalyze_after_configuring_the_key(no_key, client, monkeypatch, fake_provider):
    token = _sign_up(client, "reuser@gmail.com")
    pending = _upload(client, token=token).json()["detail"]
    assert pending["analysis_status"] == "PENDING_ANALYSIS"

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-not-secret")
    invalidate_provider()
    fake_provider(lambda image, media: _outcome(_report()))

    response = client.post(
        f"/api/scans/{pending['scan_id']}/reanalyze",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis_status"] == "COMPLETED"
    assert response.json()["verdict"] == "COUNTERFEIT SUSPECTED"


def test_reanalyze_still_blocked_without_key(no_key, client):
    token = _sign_up(client, "blocked@gmail.com")
    pending = _upload(client, token=token).json()["detail"]
    response = client.post(
        f"/api/scans/{pending['scan_id']}/reanalyze",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ANALYSIS_UNAVAILABLE"


def test_reanalyze_requires_sign_in(client):
    pending = _upload(client).json()["detail"]
    assert client.post(f"/api/scans/{pending['scan_id']}/reanalyze").status_code == 401


def test_completed_record_is_not_reanalysed(configured_key, client, fake_provider):
    fake_provider(lambda image, media: _outcome(_report()))
    token = _sign_up(client, "twice@gmail.com")
    scan_id = _upload(client, token=token).json()["id"]
    response = client.post(
        f"/api/scans/{scan_id}/reanalyze", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 409


def test_missing_key_raises_at_service_layer(no_key):
    from app.services.analysis import analyze_specimen_image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(1, 2, 3)).save(buf, format="JPEG")
    with pytest.raises(AnalysisNotConfigured):
        analyze_specimen_image(buf.getvalue(), MEDIA)
