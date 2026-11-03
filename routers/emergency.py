"""Emergency: official helpline numbers API.

The Emergency Alert page itself runs in the browser (location, saved contacts
and message drafts never touch the server), so this router only provides
reference data that pages or other clients can load.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/emergency", tags=["Emergency"])

HELPLINES: list[dict[str, str]] = [
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
        "description": "Help for women in distress.",
    },
    {
        "id": "1098",
        "name": "Child Helpline",
        "number": "1098",
        "category": "safety",
        "description": "CHILDLINE, for children in need of care and protection.",
    },
    {
        "id": "14416",
        "name": "Tele-MANAS",
        "number": "14416",
        "category": "mental-health",
        "description": "Free mental health support helpline.",
    },
]

NOTE = (
    "Numbers can change. Confirm them on the official portals (112.gov.in and the "
    "Telangana government emergency contacts page). In immediate danger, call 112 directly."
)


@router.get("/helplines")
def list_helplines(
    category: str | None = Query(
        default=None,
        pattern="^(emergency|medical|police|fire|safety|mental-health)$",
    ),
) -> dict[str, Any]:
    """Return helpline numbers, optionally filtered by category."""
    items = [h for h in HELPLINES if category is None or h["category"] == category]
    return {"count": len(items), "helplines": items, "note": NOTE}


@router.get("/helplines/{helpline_id}")
def get_helpline(helpline_id: str) -> dict[str, Any]:
    """Return one helpline by its ID."""
    for helpline in HELPLINES:
        if helpline["id"] == helpline_id:
            return {"helpline": helpline, "note": NOTE}
    raise HTTPException(status_code=404, detail="Helpline not found.")
