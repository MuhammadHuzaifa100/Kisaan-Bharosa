"""Upgrade path for databases created by the 1.0 schema.

The prototype shipped with classification/subject_name/verdict NOT NULL. Those columns
became optional once records could be stored before analysis, and SQLite cannot relax a
constraint in place, so startup rebuilds the table. These tests pin that migration,
because a broken upgrade silently turns every upload into a 500.
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text

from app.database import ensure_schema_columns

LEGACY_DDL = """
CREATE TABLE users (
    id INTEGER NOT NULL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    organization VARCHAR(255),
    district VARCHAR(100),
    created_at DATETIME NOT NULL
);
CREATE TABLE scan_records (
    id INTEGER NOT NULL,
    scan_ref VARCHAR(50) NOT NULL,
    user_id INTEGER,
    classification VARCHAR(100) NOT NULL,
    subject_name VARCHAR(255) NOT NULL,
    verdict VARCHAR(100) NOT NULL,
    confidence_score INTEGER NOT NULL,
    executive_summary TEXT NOT NULL,
    properties_json TEXT NOT NULL,
    regulatory_alignment TEXT,
    protocol_action TEXT,
    image_filename VARCHAR(255),
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id)
);
"""


@pytest.fixture
def legacy_db(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_DDL)
    conn.execute(
        "INSERT INTO scan_records (id, scan_ref, user_id, classification, subject_name, "
        "verdict, confidence_score, executive_summary, properties_json, image_filename, created_at) "
        "VALUES (1, 'REF-OLDSTAMP', NULL, 'Crop Specimen', 'Triticum aestivum', "
        "'DISEASE DETECTED', 92, 'Placeholder text written by the old engine.', '[]', "
        "'legacy.jpg', '2026-10-25 09:00:00')"
    )
    conn.commit()
    conn.close()
    return path


def _columns(path):
    conn = sqlite3.connect(path)
    info = {row[1]: row[3] for row in conn.execute("PRAGMA table_info(scan_records)")}
    conn.close()
    return info


def test_legacy_verdict_constraint_is_relaxed(legacy_db):
    assert _columns(legacy_db)["verdict"] == 1  # NOT NULL

    engine = create_engine(f"sqlite:///{legacy_db.as_posix()}")
    ensure_schema_columns(engine)

    assert _columns(legacy_db)["verdict"] == 0
    assert _columns(legacy_db)["analysis_status"] == 1


def test_legacy_row_survives_and_is_labelled_unverified(legacy_db):
    engine = create_engine(f"sqlite:///{legacy_db.as_posix()}")
    ensure_schema_columns(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT scan_ref, analysis_status, analysis_model, verdict FROM scan_records")
        ).fetchall()
    assert rows == [("REF-OLDSTAMP", "COMPLETED", "placeholder_engine", "DISEASE DETECTED")]


def test_pending_record_can_be_inserted_after_upgrade(legacy_db):
    engine = create_engine(f"sqlite:///{legacy_db.as_posix()}")
    ensure_schema_columns(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO scan_records (scan_ref, analysis_status, image_filename, created_at) "
                "VALUES ('REF-PENDING1', 'PENDING_ANALYSIS', 'new.jpg', '2026-10-25 10:00:00')"
            )
        )
    with engine.connect() as conn:
        verdictless = conn.execute(
            text("SELECT scan_ref, verdict FROM scan_records WHERE verdict IS NULL")
        ).fetchall()
    assert verdictless == [("REF-PENDING1", None)]


def test_upgrade_is_idempotent(legacy_db):
    engine = create_engine(f"sqlite:///{legacy_db.as_posix()}")
    ensure_schema_columns(engine)
    ensure_schema_columns(engine)

    inspector = sa_inspect(engine)
    assert inspector.has_table("scan_records")
    assert not inspector.has_table("scan_records__preupgrade")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM scan_records")).scalar() == 1


def test_unique_scan_reference_index_is_restored(legacy_db):
    engine = create_engine(f"sqlite:///{legacy_db.as_posix()}")
    ensure_schema_columns(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO scan_records (scan_ref, analysis_status, created_at) "
                "VALUES ('REF-DUPDUP', 'PENDING_ANALYSIS', '2026-10-25 10:00:00')"
            )
        )
    conn = sqlite3.connect(legacy_db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO scan_records (scan_ref, analysis_status, created_at) "
            "VALUES ('REF-DUPDUP', 'PENDING_ANALYSIS', '2026-10-25 10:00:01')"
        )
    conn.close()
