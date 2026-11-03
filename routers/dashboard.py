"""Dashboard summary built from appointments and medical-history records."""
from __future__ import annotations
from datetime import date
from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from database import Appointment, MedicalRecord, EmergencyHelpline, get_db, model_to_dict

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return real counts, next appointment, and recent saved activity.

    This prototype does not store vital-sign measurements, so health_metrics is
    null instead of returning fabricated readings.
    """
    today = date.today().isoformat()
    appointment_count = db.scalar(select(func.count()).select_from(Appointment)) or 0
    upcoming_count = db.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.appointment_date >= today,
            Appointment.status != "Cancelled",
        )
    ) or 0
    record_count = db.scalar(select(func.count()).select_from(MedicalRecord)) or 0
    helpline_count = db.scalar(select(func.count()).select_from(EmergencyHelpline)) or 0

    next_appointment = db.scalars(
        select(Appointment).where(
            Appointment.appointment_date >= today,
            Appointment.status != "Cancelled",
        ).order_by(Appointment.appointment_date.asc(), Appointment.appointment_time.asc())
    ).first()

    recent_appointments = db.scalars(
        select(Appointment).order_by(Appointment.created_at.desc(), Appointment.id.desc()).limit(10)
    ).all()
    recent_records = db.scalars(
        select(MedicalRecord).order_by(MedicalRecord.created_at.desc(), MedicalRecord.id.desc()).limit(10)
    ).all()

    activity: list[dict[str, Any]] = []
    for row in recent_appointments:
        activity.append({
            "type": "appointment",
            "title": "Appointment booked" if row.status != "Cancelled" else "Appointment cancelled",
            "subtitle": f"{row.doctor_name} · {row.hospital_name}",
            "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else "",
            "href": "/appointments",
            "icon": "calendar2-check",
        })
    for row in recent_records:
        activity.append({
            "type": "medical_record",
            "title": "Medical record added",
            "subtitle": f"{row.title} · {row.category}",
            "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else "",
            "href": "/medical-history",
            "icon": "clipboard2-pulse",
        })
    activity.sort(key=lambda item: item["created_at"], reverse=True)

    return {
        "status": "ok",
        "counts": {
            "appointments": appointment_count,
            "upcoming_appointments": upcoming_count,
            "medical_records": record_count,
            "helplines": helpline_count,
        },
        "next_appointment": model_to_dict(next_appointment) if next_appointment else None,
        "recent_activity": activity[:6],
        "health_metrics": None,
        "health_metrics_message": "No vital-sign measurements are configured in this prototype.",
    }
