"""Scan API behaviour with no analysis engine configured.

The engine itself is covered by tests/test_analysis_pipeline.py; this file pins the
upload validation, persistence and access rules around it.
"""

import io

import pytest
from PIL import Image

from app.config import settings
from app.models.scan import ScanRecord
from app.services.analysis import invalidate_provider


@pytest.fixture(autouse=True)
def engine_off(monkeypatch):
    """Uploads in this file must never depend on a live provider."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    invalidate_provider()
    yield
    invalidate_provider()


def _jpeg_bytes(color=(34, 139, 34), size=(200, 200)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG")
    return buf.getvalue()


def _upload(client, payload, filename="specimen.jpg", mime="image/jpeg", token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        "/api/scans/analyze",
        files={"file": (filename, payload, mime)},
        headers=headers,
    )


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _sign_up(client, email):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Test Grower"},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_upload_is_stored_as_pending_without_an_engine(client, farmer_token):
    response = _upload(client, _jpeg_bytes(), token=farmer_token)
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "ANALYSIS_UNAVAILABLE"
    assert detail["analysis_status"] == "PENDING_ANALYSIS"
    assert detail["scan_ref"].startswith("REF-")

    listing = client.get("/api/scans/", headers=_bearer(farmer_token)).json()
    match = [row for row in listing if row["id"] == detail["scan_id"]]
    assert match and match[0]["image_url"].startswith("/static/uploads/")
    assert match[0]["verdict"] is None


def test_stored_photograph_is_served_at_the_url_the_api_advertises(client, farmer_token):
    """The report page renders this URL, so it must resolve even when UPLOAD_DIR
    points somewhere other than static/uploads."""
    scan_id = _upload(client, _jpeg_bytes(), token=farmer_token).json()["detail"]["scan_id"]
    listing = client.get("/api/scans/", headers=_bearer(farmer_token)).json()
    image_url = next(row["image_url"] for row in listing if row["id"] == scan_id)

    response = client.get(image_url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_analyzing_a_non_image_is_rejected(client):
    response = _upload(client, b"just text, definitely not a jpeg")
    assert response.status_code == 400
    assert "not a readable JPEG, PNG or WEBP image" in response.json()["detail"]


@pytest.mark.parametrize(
    "filename,payload",
    [
        ("document.pdf", b"%PDF-1.4 fake"),
        ("script.html", b"<script>alert(1)</script>"),
        ("payload.svg", b"<svg onload=alert(1)></svg>"),
        ("macro.jpg", b"\xff\xd8\xff\xe0not really a jpeg"),
    ],
)
def test_non_raster_uploads_never_reach_the_storage_directory(client, filename, payload):
    response = _upload(client, payload, filename=filename)
    assert response.status_code == 400
    assert not (settings.UPLOAD_DIR / filename).exists()
    stored = [p.name for p in settings.UPLOAD_DIR.iterdir() if p.suffix in (".html", ".svg", ".pdf")]
    assert stored == []


def test_empty_upload_is_rejected(client):
    assert _upload(client, b"").status_code == 400


def test_oversized_upload_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 1024)
    response = _upload(client, _jpeg_bytes(size=(600, 600)))
    assert response.status_code == 400
    assert "maximum limit" in response.json()["detail"]


def test_png_and_webp_are_accepted(client, farmer_token):
    for mime, fmt in (("image/png", "PNG"), ("image/webp", "WEBP")):
        buf = io.BytesIO()
        Image.new("RGB", (120, 120), color=(9, 9, 9)).save(buf, format=fmt)
        response = _upload(client, buf.getvalue(), filename=f"x.{fmt.lower()}", mime=mime, token=farmer_token)
        assert response.status_code == 503, response.text  # pending, not rejected
        assert response.json()["detail"]["code"] == "ANALYSIS_UNAVAILABLE"


def test_scan_history_requires_sign_in(client, farmer_token):
    _upload(client, _jpeg_bytes(), token=farmer_token)
    assert client.get("/api/scans/").status_code == 401
    assert client.get("/api/scans/?analysis_status=PENDING_ANALYSIS").status_code == 401


def test_grower_sees_only_their_own_scans(client, farmer_token):
    other = _sign_up(client, "neighbour@gmail.com")
    mine = _upload(client, _jpeg_bytes(), token=farmer_token).json()["detail"]

    theirs = client.get("/api/scans/", headers=_bearer(other)).json()
    assert [row["id"] for row in theirs] == []
    assert client.get("/api/scans/?q=Wheat", headers=_bearer(other)).json() == []
    assert client.get(f"/api/scans/{mine['scan_id']}", headers=_bearer(other)).status_code == 404


def test_inspector_sees_the_whole_register(client, farmer_token, inspector_token):
    mine = _upload(client, _jpeg_bytes(), token=farmer_token).json()["detail"]
    listed = client.get("/api/scans/", headers=_bearer(inspector_token)).json()
    assert mine["scan_id"] in [row["id"] for row in listed]
    assert client.get(f"/api/scans/{mine['scan_id']}", headers=_bearer(inspector_token)).status_code == 200


def test_filters_apply_within_the_callers_scope(client, farmer_token):
    ref = _upload(client, _jpeg_bytes(), token=farmer_token).json()["detail"]["scan_ref"]
    assert [r["scan_ref"] for r in client.get(f"/api/scans/?q={ref}", headers=_bearer(farmer_token)).json()] == [ref]
    assert client.get("/api/scans/?verdict=INCONCLUSIVE", headers=_bearer(farmer_token)).json() == []
    assert len(client.get("/api/scans/?analysis_status=PENDING_ANALYSIS", headers=_bearer(farmer_token)).json()) == 1


def test_get_nonexistent_scan(client, farmer_token):
    assert client.get("/api/scans/999999", headers=_bearer(farmer_token)).status_code == 404


def test_engine_status_endpoint(client, farmer_token):
    body = client.get("/api/scans/engine/status").json()
    assert body["configured"] is False
    assert body["records_awaiting_analysis"] == 0

    _upload(client, _jpeg_bytes(), token=farmer_token)
    assert client.get("/api/scans/engine/status").json()["records_awaiting_analysis"] == 1


def test_repeated_scans_are_throttled(client, farmer_token, monkeypatch):
    """Every call bills the provider, so one grower cannot drain the budget."""
    monkeypatch.setattr(settings, "ANALYSIS_RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(settings, "ANALYSIS_RATE_LIMIT_WINDOW_SECONDS", 60)

    assert _upload(client, _jpeg_bytes(), token=farmer_token).status_code == 503
    assert _upload(client, _jpeg_bytes(), token=farmer_token).status_code == 503

    blocked = _upload(client, _jpeg_bytes(), token=farmer_token)
    assert blocked.status_code == 429
    detail = blocked.json()["detail"]
    assert detail["code"] == "RATE_LIMITED"
    assert detail["retryable"] is True
    assert 1 <= detail["retry_after"] <= 60
    assert blocked.headers["Retry-After"] == str(detail["retry_after"])
    assert len(client.get("/api/scans/", headers=_bearer(farmer_token)).json()) == 2


def test_delete_scan_requires_sign_in(client, farmer_token):
    scan_id = _upload(client, _jpeg_bytes(), token=farmer_token).json()["detail"]["scan_id"]
    assert client.delete(f"/api/scans/{scan_id}").status_code == 401


def test_another_grower_cannot_delete_your_scan(client, farmer_token):
    other = _sign_up(client, "remover@gmail.com")
    scan_id = _upload(client, _jpeg_bytes(), token=farmer_token).json()["detail"]["scan_id"]

    assert client.delete(f"/api/scans/{scan_id}", headers=_bearer(other)).status_code == 404
    assert client.get(f"/api/scans/{scan_id}", headers=_bearer(farmer_token)).status_code == 200


def test_delete_scan_removes_record_and_file(client, db_session, farmer_token):
    scan_id = _upload(client, _jpeg_bytes(), token=farmer_token).json()["detail"]["scan_id"]
    record = db_session.query(ScanRecord).filter(ScanRecord.id == scan_id).one()
    image_path = settings.UPLOAD_DIR / record.image_filename
    assert image_path.exists()

    response = client.delete(f"/api/scans/{scan_id}", headers=_bearer(farmer_token))
    assert response.status_code == 204
    assert client.get(f"/api/scans/{scan_id}", headers=_bearer(farmer_token)).status_code == 404
    assert not image_path.exists()
