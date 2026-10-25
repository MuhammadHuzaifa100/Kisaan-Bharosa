import os
import tempfile

# Settings are read at import time, so the sandbox has to exist before app.main is loaded:
# without this a test run writes rows into the developer's kisaan_bharosa.db and dumps
# uploaded images into static/uploads/.
_TEST_SANDBOX = tempfile.mkdtemp(prefix="kisaan-bharosa-tests-")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["UPLOAD_DIR"] = os.path.join(_TEST_SANDBOX, "uploads")
os.environ["GEMINI_API_KEY"] = ""

import io
from datetime import datetime, timezone
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.config import settings
from app.database import Base, get_db
from app.services.auth_service import hash_password
from app.models.user import User
from app.models.product import OfficialProduct
from app.models.scan import ScanRecord
from app.models.fraud_report import FraudReport
from app.services.rate_limit import analysis_limiter, complaint_limiter
from main import app

assert str(settings.UPLOAD_DIR).replace("\\", "/").startswith(_TEST_SANDBOX.replace("\\", "/")), (
    "test uploads are writing outside the sandbox"
)

# In-memory SQLite database for test isolation
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    # Seed initial test data
    db = TestingSessionLocal()
    try:
        # Seed test inspector
        inspector = User(
            email="test_inspector@kisaan.pk",
            hashed_password=hash_password("InspectorPass123!"),
            full_name="Inspector Test",
            role="inspector",
            organization="Quality Bureau",
            district="Lahore",
        )
        # Seed test farmer
        farmer = User(
            email="test_farmer@kisaan.pk",
            hashed_password=hash_password("FarmerPass123!"),
            full_name="Farmer Test",
            role="farmer",
            organization="Farm Alpha",
            district="Multan",
        )
        # Seed test official products
        products = [
            OfficialProduct(
                brand_name="Sona Urea (Prilled)",
                category="Urea Fertilizer",
                manufacturer="Fauji Fertilizer Company Ltd.",
                bag_size="50 kg bag",
                official_mrp_pkr=4650,
                subsidy_amount_pkr=500,
                psqca_license_no="PSQCA/CM/L-0892",
                security_features="Reflective multi-angle hologram stitch line",
            ),
            OfficialProduct(
                brand_name="Sona DAP",
                category="Phosphate Fertilizer",
                manufacturer="FFC - Jordan Fertilizer JV",
                bag_size="50 kg bag",
                official_mrp_pkr=12800,
                subsidy_amount_pkr=1000,
                psqca_license_no="PSQCA/CM/L-1104",
                security_features="Embossed batch verification QR-matrix",
            ),
        ]
        db.add_all([inspector, farmer] + products)
        db.commit()
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="function", autouse=True)
def clean_slate(db_session):
    """Each test starts with no scans or complaints and an unused analysis budget.

    The seeded accounts and product registry stay; only rows that tests create go away, so
    listing assertions describe one test's data instead of the whole suite's.
    """
    db_session.query(ScanRecord).delete()
    db_session.query(FraudReport).delete()
    db_session.commit()
    analysis_limiter.reset()
    complaint_limiter.reset()
    yield

@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

@pytest.fixture
def inspector_token(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "test_inspector@kisaan.pk", "password": "InspectorPass123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]

@pytest.fixture
def farmer_token(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "test_farmer@kisaan.pk", "password": "FarmerPass123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]

@pytest.fixture
def sample_image_bytes():
    """Generate a valid in-memory JPEG image for testing."""
    img = Image.new("RGB", (200, 200), color=(34, 139, 34))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()
