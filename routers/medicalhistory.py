"""Medical history: request model and API routes (MySQL via SQLAlchemy)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import MedicalRecord, get_db, ist_now, model_to_dict

logger = logging.getLogger("healthcare_assistant")


# ============================================================
# REQUEST MODEL
# ============================================================

MEDICAL_CATEGORIES = ("condition", "medication", "allergy", "surgery", "visit", "report")
MEDICAL_STATUSES = (
    "Recorded", "Ongoing", "Resolved", "Taking",
    "Stopped", "Known allergy", "Completed", "Follow-up needed",
)


class MedicalRecordCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: str
    title: str = Field(min_length=2, max_length=180)
    recorded_date: str
    provider: str = Field(default="", max_length=150)
    facility: str = Field(default="", max_length=180)
    status: str = Field(default="Recorded", max_length=40)
    description: str = Field(default="", max_length=3000)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in MEDICAL_CATEGORIES:
            raise ValueError("Choose a valid record type.")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in MEDICAL_STATUSES:
            raise ValueError("Choose a valid status.")
        return value

    @field_validator("recorded_date")
    @classmethod
    def validate_recorded_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Choose a valid record date.") from exc
        if parsed > ist_now().date():
            raise ValueError("Record date cannot be in the future.")
        return value


# ============================================================
# ROUTES
# ============================================================

router = APIRouter(prefix="/api/medical-history", tags=["Medical history"])


@router.get("")
def list_medical_history(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return all records (newest first) plus a count per category."""
    rows = db.scalars(
        select(MedicalRecord).order_by(
            MedicalRecord.recorded_date.desc(), MedicalRecord.id.desc()
        )
    ).all()
    records = [model_to_dict(row) for row in rows]

    summary = {category: 0 for category in MEDICAL_CATEGORIES}
    for record in records:
        if record["category"] in summary:
            summary[record["category"]] += 1
    return {"count": len(records), "summary": summary, "records": records}


@router.post("", status_code=201)
def create_medical_record(
    data: MedicalRecordCreate, db: Session = Depends(get_db)
) -> dict[str, Any]:
    record = MedicalRecord(**data.model_dump())
    db.add(record)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Medical history database error: %s", exc)
        raise HTTPException(
            status_code=500, detail="Could not save the record. Please try again."
        ) from exc

    db.refresh(record)
    return {"message": "Medical record saved successfully.", "record": model_to_dict(record)}


@router.delete("/{record_id}")
def delete_medical_record(record_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    record = db.get(MedicalRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found.")
    try:
        db.delete(record)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Medical history delete error: %s", exc)
        raise HTTPException(
            status_code=500, detail="Could not delete the record. Please try again."
        ) from exc
    return {"message": "Record deleted successfully."}