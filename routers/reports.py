"""Medical report upload API: files on disk, metadata in the database."""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import MedicalReportUpload, get_db

logger = logging.getLogger("healthcare_assistant.reports")
router = APIRouter(prefix="/api/reports", tags=["Medical Reports"])

# <project folder>\uploads\medical_reports
BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = BASE_DIR / "uploads" / "medical_reports"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Check both extension and file signature; never trust the browser MIME type alone.
ALLOWED_FILES: dict[str, tuple[str, bytes]] = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}


def report_to_dict(report: MedicalReportUpload) -> dict[str, Any]:
    return {
        "id": report.id,
        "title": report.title,
        "original_filename": report.original_filename,
        "content_type": report.content_type,
        "file_size": report.file_size,
        "uploaded_at": report.uploaded_at.isoformat(timespec="seconds"),
        "download_url": f"/api/reports/{report.id}/download",
    }


# Plain `def` (not `async def`): FastAPI runs it in a worker thread, so the
# blocking file write and database calls never stall the event loop.
@router.post("/upload", status_code=201)
def upload_medical_report(
    file: UploadFile = File(...),
    title: str = Form("Medical Report", max_length=180),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Keep only the last path segment, whether the browser sent "/" or "\" separators.
    original_filename = (re.split(r"[\\/]", file.filename or "report")[-1] or "report")[:255]
    extension = Path(original_filename).suffix.lower()

    if extension not in ALLOWED_FILES:
        file.file.close()
        raise HTTPException(415, "Upload PDF, PNG, JPG, or JPEG files only.")

    try:
        content = file.file.read(MAX_FILE_SIZE + 1)
    finally:
        file.file.close()

    if not content:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "Maximum file size is 10 MB.")

    content_type, signature = ALLOWED_FILES[extension]
    if not content.startswith(signature):
        raise HTTPException(415, "File content does not match its extension.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid.uuid4().hex}{extension}"
    destination = UPLOAD_DIR / stored_filename

    try:
        destination.write_bytes(content)
        report = MedicalReportUpload(
            title=title.strip() or "Medical Report",
            original_filename=original_filename,
            stored_filename=stored_filename,
            content_type=content_type,
            file_size=len(content),
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return {"message": "Medical report uploaded successfully.", "report": report_to_dict(report)}
    except Exception as exc:
        db.rollback()
        destination.unlink(missing_ok=True)  # don't leave an orphan file behind
        logger.exception("Medical report upload failed")
        raise HTTPException(500, "Could not save the medical report.") from exc


@router.get("")
def list_medical_reports(db: Session = Depends(get_db)) -> dict[str, Any]:
    reports = db.scalars(
        select(MedicalReportUpload).order_by(
            MedicalReportUpload.uploaded_at.desc(), MedicalReportUpload.id.desc()
        )
    ).all()
    return {"count": len(reports), "reports": [report_to_dict(item) for item in reports]}


@router.get("/{report_id}/download")
def download_medical_report(
    report_id: int,
    disposition: str = Query("attachment", pattern="^(attachment|inline)$"),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download a report. Use ?disposition=inline to view PDFs/images in the browser."""
    report = db.get(MedicalReportUpload, report_id)
    if report is None:
        raise HTTPException(404, "Medical report not found.")

    root = UPLOAD_DIR.resolve()
    path = (UPLOAD_DIR / report.stored_filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "Report file is missing.")

    return FileResponse(
        path=path,
        media_type=report.content_type,
        filename=report.original_filename,
        content_disposition_type=disposition,
    )


@router.delete("/{report_id}")
def delete_medical_report(report_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    report = db.get(MedicalReportUpload, report_id)
    if report is None:
        raise HTTPException(404, "Medical report not found.")

    path = UPLOAD_DIR / report.stored_filename
    try:
        db.delete(report)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Could not delete medical report")
        raise HTTPException(500, "Could not delete report.") from exc

    path.unlink(missing_ok=True)
    return {"message": "Medical report deleted successfully."}