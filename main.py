import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.config import settings
from app.database import Base, engine, ensure_schema_columns, SessionLocal
from app.models.product import OfficialProduct
from app.routers import auth_router, scan_router, report_router, directory_router, analytics_router
from app.services.auth_service import ensure_bootstrap_inspector

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("kisaan_bharosa")

def seed_initial_data():
    """Seed the certified product registry and any operator-provided staff account."""
    db = SessionLocal()
    try:
        ensure_bootstrap_inspector(db)

        # Official Subsidized Products & PSQCA Registry
        if db.query(OfficialProduct).count() == 0:
            initial_products = [
                OfficialProduct(
                    brand_name="Sona Urea (Prilled)",
                    category="Urea Fertilizer",
                    manufacturer="Fauji Fertilizer Company Ltd.",
                    bag_size="50 kg bag",
                    official_mrp_pkr=4650,
                    subsidy_amount_pkr=500,
                    psqca_license_no="PSQCA/CM/L-0892",
                    security_features="Reflective multi-angle hologram stitch line, micro-dot batch coding, high-density polyethylene moisture seal",
                ),
                OfficialProduct(
                    brand_name="Engro Urea (Granular)",
                    category="Urea Fertilizer",
                    manufacturer="Engro Fertilizers Limited",
                    bag_size="50 kg bag",
                    official_mrp_pkr=4650,
                    subsidy_amount_pkr=500,
                    psqca_license_no="PSQCA/CM/L-0411",
                    security_features="Tamper-evident thermal color-shift monogram, continuous inkjet date stamp, UV luminescent fiber weave",
                ),
                OfficialProduct(
                    brand_name="Sona DAP (Di-Ammonium Phosphate)",
                    category="Phosphate Fertilizer",
                    manufacturer="FFC - Jordan Fertilizer JV",
                    bag_size="50 kg bag",
                    official_mrp_pkr=12800,
                    subsidy_amount_pkr=1000,
                    psqca_license_no="PSQCA/CM/L-1104",
                    security_features="Embossed batch verification QR-matrix, anti-counterfeit woven thread, registered GOP subsidy stamp",
                ),
                OfficialProduct(
                    brand_name="Sarsabz CAN (Calcium Ammonium Nitrate)",
                    category="Nitrogen Fertilizer",
                    manufacturer="Fatima Fertilizer Company",
                    bag_size="50 kg bag",
                    official_mrp_pkr=4100,
                    subsidy_amount_pkr=350,
                    psqca_license_no="PSQCA/CM/L-0789",
                    security_features="Registered green-stripe security band, laser-etched manufacturer lot sequence",
                ),
                OfficialProduct(
                    brand_name="Akbar-2019 Certified Wheat Seed",
                    category="Certified Seed",
                    manufacturer="Punjab Seed Corporation",
                    bag_size="50 kg bag",
                    official_mrp_pkr=5200,
                    subsidy_amount_pkr=1200,
                    psqca_license_no="FSC&RD-PK-WHT-2019",
                    security_features="Blue certified seed tag with embossed FSC&RD seal, barcode batch tracking, heat-sealed bag mouth",
                ),
                OfficialProduct(
                    brand_name="CKC-05 BT Cotton Certified Seed",
                    category="Certified Seed",
                    manufacturer="Central Cotton Research Institute",
                    bag_size="20 kg bag",
                    official_mrp_pkr=6800,
                    subsidy_amount_pkr=800,
                    psqca_license_no="NBC-GOP-COT-05",
                    security_features="Pink hybrid tag with National Biosafety Committee clearance hologram and serial register",
                ),
            ]
            db.add_all(initial_products)
        db.commit()
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema_columns()
    seed_initial_data()
    logger.info(
        "%s started (env=%s, ai=%s)",
        settings.APP_NAME,
        settings.ENVIRONMENT,
        "configured" if settings.ai_configured else "NOT configured",
    )
    yield

app = FastAPI(
    title="Kisaan Bharosa - Agricultural Quality & Diagnostic Platform",
    description="Laboratory-Grade Agricultural Input Authentication & Phytosanitary Diagnostics Portal",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for API clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials="*" not in settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace or internal detail to the client."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected internal error occurred. Please try again."},
    )

@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Database error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is temporarily unavailable. Please try again."},
    )

# Mount static files (Uploads, CSS, JS)
static_path = Path(__file__).resolve().parent / "static"
static_path.mkdir(parents=True, exist_ok=True)
# Registered ahead of /static so a relocated UPLOAD_DIR still serves the
# /static/uploads/<name> URLs the scan API returns.
app.mount("/static/uploads", StaticFiles(directory=str(settings.UPLOAD_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Include Modular Routers
app.include_router(auth_router.router)
app.include_router(scan_router.router)
app.include_router(report_router.router)
app.include_router(directory_router.router)
app.include_router(analytics_router.router)

# Serve Web Single Page Application
templates_dir = Path(__file__).resolve().parent / "templates"

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    index_file = templates_dir / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Kisaan Bharosa Backend Active</h1><p>API docs at <a href='/docs'>/docs</a></p>")

@app.get("/health")
def health_check():
    """Liveness plus a real database round-trip and AI readiness flag."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database_ok = True
    except SQLAlchemyError:
        logger.exception("Health check failed: database unreachable")
        database_ok = False

    status_code = 200 if database_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if database_ok else "degraded",
            "service": settings.APP_NAME,
            "environment": settings.ENVIRONMENT,
            "database": "connected" if database_ok else "unreachable",
            "analysis_engine": "ready" if settings.ai_configured else "no_api_key",
        },
    )
