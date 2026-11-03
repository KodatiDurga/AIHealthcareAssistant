"""Appointments: request model and API routes (MySQL via SQLAlchemy)."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import Appointment, get_db, ist_now, make_slot_key, model_to_dict

logger = logging.getLogger("healthcare_assistant")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,25}$")


# ============================================================
# REQUEST MODEL
# ============================================================

class AppointmentCreate(BaseModel):
    # Strips leading/trailing whitespace so "  " cannot pass min_length.
    model_config = ConfigDict(str_strip_whitespace=True)

    patient_name: str = Field(min_length=2, max_length=100)
    patient_email: str = Field(min_length=5, max_length=160)
    patient_phone: str = Field(min_length=7, max_length=25)
    hospital_name: str = Field(min_length=2, max_length=180)
    hospital_address: str = Field(default="", max_length=500)
    hospital_lat: float | None = None
    hospital_lon: float | None = None
    doctor_name: str = Field(min_length=2, max_length=100)
    specialty: str = Field(min_length=2, max_length=100)
    appointment_date: str
    appointment_time: str
    reason: str = Field(default="", max_length=1000)

    @field_validator("patient_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not EMAIL_RE.match(value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("patient_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not PHONE_RE.match(value):
            raise ValueError("Enter a valid phone number.")
        return value

    @field_validator("hospital_lat")
    @classmethod
    def validate_hospital_lat(cls, value: float | None) -> float | None:
        if value is not None and not -90 <= value <= 90:
            raise ValueError("Hospital latitude must be between -90 and 90.")
        return value

    @field_validator("hospital_lon")
    @classmethod
    def validate_hospital_lon(cls, value: float | None) -> float | None:
        if value is not None and not -180 <= value <= 180:
            raise ValueError("Hospital longitude must be between -180 and 180.")
        return value

    @field_validator("appointment_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Choose a valid appointment date.") from exc
        if parsed < ist_now().date():
            raise ValueError("Appointment date cannot be in the past.")
        return value

    @field_validator("appointment_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError("Choose a valid appointment time.") from exc
        return value

    @model_validator(mode="after")
    def validate_not_earlier_today(self) -> "AppointmentCreate":
        now = ist_now()
        if date.fromisoformat(self.appointment_date) == now.date():
            chosen = datetime.strptime(self.appointment_time, "%H:%M").time()
            if chosen <= now.time():
                raise ValueError("Choose a time later today, or pick another date.")
        return self


# ============================================================
# ROUTES
# ============================================================

router = APIRouter(prefix="/api/appointments", tags=["Appointments"])


@router.get("")
def list_appointments(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(
        select(Appointment).order_by(
            Appointment.appointment_date.asc(),
            Appointment.appointment_time.asc(),
            Appointment.id.desc(),
        )
    ).all()
    appointments = [model_to_dict(row) for row in rows]
    return {"count": len(appointments), "appointments": appointments}


@router.post("", status_code=201)
def create_appointment(
    data: AppointmentCreate, db: Session = Depends(get_db)
) -> dict[str, Any]:
    appointment = Appointment(
        **data.model_dump(),
        status="Scheduled",
        slot_key=make_slot_key(
            data.doctor_name,
            data.hospital_name,
            data.appointment_date,
            data.appointment_time,
        ),
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="That doctor already has an appointment at this hospital for the selected date and time.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Appointment database error: %s", exc)
        raise HTTPException(
            status_code=500, detail="Could not save the appointment. Please try again."
        ) from exc

    db.refresh(appointment)
    return {
        "message": "Appointment booked successfully.",
        "appointment": model_to_dict(appointment),
    }


@router.patch("/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: int, db: Session = Depends(get_db)
) -> dict[str, str]:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if appointment.status == "Cancelled":
        raise HTTPException(status_code=409, detail="Appointment is already cancelled.")

    appointment.status = "Cancelled"
    appointment.slot_key = None  # frees the slot for new bookings
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Appointment cancel error: %s", exc)
        raise HTTPException(
            status_code=500, detail="Could not cancel the appointment. Please try again."
        ) from exc
    return {"message": "Appointment cancelled successfully."}


@router.get("/{appointment_id}")
def get_appointment(appointment_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    return {"appointment": model_to_dict(appointment)}