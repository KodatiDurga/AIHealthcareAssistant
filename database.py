"""Database configuration and SQLAlchemy models for AI Healthcare Assistant.

Configure MySQL in .env and run the app with:
    python -m uvicorn main:app --reload

This file defines each model exactly once. init_db() creates missing tables;
it does not alter existing table definitions or delete existing data.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Generator

from dotenv import load_dotenv
from sqlalchemy import (
    URL,
    JSON,
    ForeignKey,
    Index,
    Integer,
    Float,
    String,
    DateTime,
    Text,
    create_engine,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

load_dotenv()


# =========================================================
# DATABASE CONFIGURATION
# =========================================================

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "healthcare_assistant")
SQL_ECHO = os.getenv("SQL_ECHO", "false").strip().lower() == "true"

DATABASE_URL = URL.create(
    drivername="mysql+pymysql",
    username=MYSQL_USER,
    password=MYSQL_PASSWORD,
    host=MYSQL_HOST,
    port=MYSQL_PORT,
    database=MYSQL_DATABASE,
    query={"charset": "utf8mb4"},
)

engine = create_engine(
    DATABASE_URL,
    echo=SQL_ECHO,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


# =========================================================
# BASE AND TIMEZONE
# =========================================================

class Base(DeclarativeBase):
    pass


IST = timezone(timedelta(hours=5, minutes=30))


def ist_now() -> datetime:
    """Return India Standard Time as a naive datetime for MySQL DATETIME."""
    return datetime.now(IST).replace(tzinfo=None)


# =========================================================
# APPOINTMENTS
# =========================================================

class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_name: Mapped[str] = mapped_column(String(100), nullable=False)
    patient_email: Mapped[str] = mapped_column(String(160), nullable=False)
    patient_phone: Mapped[str] = mapped_column(String(25), nullable=False)

    hospital_name: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    hospital_address: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    hospital_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    hospital_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    doctor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    specialty: Mapped[str] = mapped_column(String(100), nullable=False)
    appointment_date: Mapped[str] = mapped_column(String(10), nullable=False)
    appointment_time: Mapped[str] = mapped_column(String(5), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Scheduled")

    # Set slot_key to None when cancelled. MySQL unique indexes allow multiple NULLs.
    slot_key: Mapped[str | None] = mapped_column(String(400), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=ist_now, nullable=False)

    __table_args__ = (
        Index("ix_appointments_date_time", "appointment_date", "appointment_time"),
    )


def make_slot_key(
    doctor_name: str,
    hospital_name: str,
    appointment_date: str,
    appointment_time: str,
) -> str:
    """Build a normalized key for an active doctor/hospital/date/time slot."""
    return "|".join(
        (
            doctor_name.strip().lower(),
            hospital_name.strip().lower(),
            appointment_date,
            appointment_time,
        )
    )


# =========================================================
# MEDICAL HISTORY
# =========================================================

class MedicalRecord(Base):
    # Keep this name consistent with the existing medical-history API.
    __tablename__ = "medical_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    recorded_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    facility: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="Recorded")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=ist_now, nullable=False)


# =========================================================
# EMERGENCY HELPLINES
# =========================================================

class EmergencyHelpline(Base):
    __tablename__ = "emergency_helplines"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=ist_now, nullable=False)


DEFAULT_EMERGENCY_HELPLINES: list[dict[str, str]] = [
    {
        "id": "112",
        "name": "National Emergency Number",
        "number": "112",
        "category": "emergency",
        "description": "Police, fire, ambulance and other emergency response (India).",
    },
    {
        "id": "108",
        "name": "Emergency Ambulance",
        "number": "108",
        "category": "medical",
        "description": "State emergency ambulance service (Telangana).",
    },
    {
        "id": "102",
        "name": "Ambulance (Patient Transport)",
        "number": "102",
        "category": "medical",
        "description": "Government ambulance and patient transport service.",
    },
    {
        "id": "100",
        "name": "Police",
        "number": "100",
        "category": "police",
        "description": "Police control room.",
    },
    {
        "id": "101",
        "name": "Fire",
        "number": "101",
        "category": "fire",
        "description": "Fire and rescue services.",
    },
    {
        "id": "1091",
        "name": "Women Helpline",
        "number": "1091",
        "category": "safety",
        "description": "Help for women in distress; verify current local applicability.",
    },
    {
        "id": "1098",
        "name": "Child Helpline",
        "number": "1098",
        "category": "safety",
        "description": "Child helpline for children needing care and protection.",
    },
    {
        "id": "14416",
        "name": "Tele-MANAS",
        "number": "14416",
        "category": "mental-health",
        "description": "Mental health support helpline.",
    },
]


# =========================================================
# TRUSTED EMERGENCY CONTACTS
# =========================================================

class TrustedEmergencyContact(Base):
    """Prototype contacts keyed by a browser-generated client ID.

    A client ID is not authentication. Add real user authentication and ownership
    checks before using this table for a public or multi-user deployment.
    """
    __tablename__ = "trusted_emergency_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    phone: Mapped[str] = mapped_column(String(25), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=ist_now, nullable=False)

    __table_args__ = (
        Index("ix_trusted_emergency_contacts_client_id", "client_id"),
        Index(
            "uq_trusted_emergency_contacts_client_phone",
            "client_id",
            "phone",
            unique=True,
        ),
    )


# =========================================================
# UPLOADED MEDICAL REPORT METADATA
# =========================================================

class MedicalReportUpload(Base):
    """Metadata for report files saved on disk under uploads/medical_reports."""
    __tablename__ = "medical_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False, default="Medical Report")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=ist_now, nullable=False, index=True
    )


# =========================================================
# MEDICAL REPORT EXTRACTION AND COMPARISON RESULTS
# =========================================================

class MedicalReportAnalysis(Base):
    """Extracted report text, structured findings, and comparison details."""
    __tablename__ = "medical_report_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("medical_reports.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    report_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    extracted_text: Mapped[str] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql"), nullable=False, default=""
    )
    findings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    previous_report_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("medical_reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    comparison_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    analysis_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=ist_now, nullable=False)

    __table_args__ = (
        Index("ix_medical_report_analyses_previous_report_id", "previous_report_id"),
    )


# =========================================================
# SERIALIZATION HELPER
# =========================================================

def model_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy model row to a JSON-friendly dictionary."""
    result: dict[str, Any] = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if isinstance(value, datetime):
            value = value.isoformat(timespec="seconds")
        result[column.name] = value
    result.pop("slot_key", None)
    return result


# =========================================================
# CREATE TABLES AND SEED REFERENCE HELPLINES
# =========================================================

def init_db() -> None:
    """Create missing tables and insert any missing emergency helpline rows.

    create_all() does not alter existing tables. Use a migration for schema changes.
    """
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        try:
            for item in DEFAULT_EMERGENCY_HELPLINES:
                if db.get(EmergencyHelpline, item["id"]) is None:
                    db.add(EmergencyHelpline(**item))
            db.commit()
        except Exception:
            db.rollback()
            raise


# =========================================================
# FASTAPI DATABASE DEPENDENCY
# =========================================================

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
