"""
AI Healthcare Assistant - Application Entry Point.

Run with:
    python -m uvicorn main:app --reload
"""

from __future__ import annotations
from routers import appointments, emergency, medicalhistory, nearby, reports
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from database import init_db
from routers import (
    appointments,
    emergency,
    medicalhistory,
    nearby,
    reports,
)
from routers import report_comparison

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(level=logging.INFO)

logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger("healthcare_assistant")


# =========================================================
# APPLICATION PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


# =========================================================
# APPLICATION LIFESPAN
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MySQL tables when the application starts."""

    logger.info("Starting AI Healthcare Assistant")

    try:
        init_db()
        logger.info("Database initialized successfully")

    except Exception:
        logger.exception("Database initialization failed")
        raise

    yield

    logger.info("AI Healthcare Assistant stopped")


# =========================================================
# CREATE FASTAPI APPLICATION
# =========================================================

app = FastAPI(
    title="AI Healthcare Assistant",
    description=(
        "Healthcare application providing hospital discovery, "
        "appointment booking, medical history, emergency assistance, "
        "and medical report uploads."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# =========================================================
# REGISTER API ROUTERS
# Register every router only once.
# =========================================================

app.include_router(appointments.router)

app.include_router(medicalhistory.router)

app.include_router(nearby.router)

app.include_router(emergency.router)

# Medical report upload, listing, download, and delete APIs
app.include_router(reports.router)
app.include_router(medicalhistory.router)
app.include_router(report_comparison.router)
# =========================================================
# HTML PAGE HELPER
# =========================================================

def serve_page(filename: str) -> FileResponse:
    """Return an HTML file from the templates directory."""

    path = TEMPLATES_DIR / filename

    if not path.is_file():
        logger.error("Page not found: %s", path)

        raise HTTPException(
            status_code=404,
            detail=f"{filename} not found.",
        )

    return FileResponse(path)


# =========================================================
# FRONTEND PAGES
# =========================================================

@app.get("/", include_in_schema=False)
def home_page() -> FileResponse:
    """Main healthcare dashboard."""
    return serve_page("index.html")


@app.get("/appointments", include_in_schema=False)
def appointments_page() -> FileResponse:
    """Appointment booking page."""
    return serve_page("appointments.html")


@app.get("/medical-history", include_in_schema=False)
def medical_history_page() -> FileResponse:
    """Medical history page."""
    return serve_page("medical-history.html")


@app.get("/emergency-alert", include_in_schema=False)
def emergency_alert_page() -> FileResponse:
    """Emergency alert page."""
    return serve_page("emergency-alert.html")


@app.get("/upload-medical-report", include_in_schema=False)
def upload_medical_report_page() -> FileResponse:
    """Medical report upload page."""
    return serve_page("upload-medical-report.html")


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/api/health", tags=["Health"])
def health() -> dict[str, str]:
    """Check whether the application API is responding."""

    return {
        "status": "ok",
        "application": "AI Healthcare Assistant",
    }

@app.get("/report-comparison", include_in_schema=False)
def report_comparison_page() -> FileResponse:
    return serve_page("report-comparison.html")