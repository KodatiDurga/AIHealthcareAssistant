
"""Medical report extraction and comparison API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import (
    MedicalReportAnalysis,
    MedicalReportUpload,
    get_db,
    ist_now,
)

from services.report_analysis import (
    analyze_report_file,
    build_summary,
    compare_with_previous_report,
)

from services.ai_explanation import (
    generate_ai_explanation,
)


logger = logging.getLogger(
    "healthcare_assistant.report_comparison"
)

router = APIRouter(
    prefix="/api/report-comparison",
    tags=["Medical Report Analysis and Comparison"],
)

PROJECT_DIR = Path(__file__).resolve().parents[1]

UPLOAD_DIR = (
    PROJECT_DIR / "uploads" / "medical_reports"
)

MAX_PREVIOUS_REPORTS_TO_CHECK = 50


# =========================================================
# REQUEST MODEL
# =========================================================

class CompareReportsRequest(BaseModel):

    previous_report_id: int = Field(gt=0)

    latest_report_id: int = Field(gt=0)


# =========================================================
# FILE PATH VALIDATION
# =========================================================

def get_report_path(
    report: MedicalReportUpload,
) -> Path:

    root = UPLOAD_DIR.resolve()

    stored_name = Path(
        report.stored_filename
    ).name

    if stored_name != report.stored_filename:

        raise HTTPException(
            status_code=400,
            detail="Invalid stored report filename.",
        )

    path = (
        root / stored_name
    ).resolve()

    if path.parent != root or not path.is_file():

        raise HTTPException(
            status_code=404,
            detail="Uploaded report file is missing.",
        )

    return path


# =========================================================
# RESPONSE SERIALIZATION
# =========================================================

def analysis_to_dict(
    analysis: MedicalReportAnalysis,
) -> dict[str, Any]:

    return {
        "report_id": analysis.report_id,
        "report_type": analysis.report_type,
        "extraction_method": analysis.extraction_method,
        "findings": analysis.findings_json or [],
        "previous_report_id": analysis.previous_report_id,
        "comparisons": analysis.comparison_json or [],
        "summary": analysis.summary,
        "analysis_status": analysis.analysis_status,
        "analyzed_at": analysis.created_at.isoformat(
            timespec="seconds"
        ),
    }


# =========================================================
# EXTRACT AND SAVE REPORT
# =========================================================

def extract_and_store(
    db: Session,
    report: MedicalReportUpload,
) -> MedicalReportAnalysis:

    path = get_report_path(report)

    extracted = analyze_report_file(
        path=path,
        content_type=report.content_type or "",
        title=report.title or "Medical Report",
        filename=(
            report.original_filename
            or report.stored_filename
        ),
    )

    analysis = db.scalar(
        select(MedicalReportAnalysis).where(
            MedicalReportAnalysis.report_id == report.id
        )
    )

    if analysis is None:

        analysis = MedicalReportAnalysis(
            report_id=report.id,
            report_type=extracted["report_type"],
            extraction_method=extracted["extraction_method"],
            extracted_text=extracted["extracted_text"],
            findings_json=extracted["findings"],
            previous_report_id=None,
            comparison_json=[],
            summary="",
            analysis_status="extracted",
            created_at=ist_now(),
        )

        db.add(analysis)

    else:

        analysis.report_type = extracted["report_type"]

        analysis.extraction_method = (
            extracted["extraction_method"]
        )

        analysis.extracted_text = (
            extracted["extracted_text"]
        )

        analysis.findings_json = (
            extracted["findings"]
        )

        analysis.previous_report_id = None
        analysis.comparison_json = []
        analysis.summary = ""
        analysis.analysis_status = "extracted"
        analysis.created_at = ist_now()

    db.flush()

    return analysis


# =========================================================
# GET OR EXTRACT EXISTING ANALYSIS
# =========================================================

def get_or_extract(
    db: Session,
    report: MedicalReportUpload,
) -> MedicalReportAnalysis:

    analysis = db.scalar(
        select(MedicalReportAnalysis).where(
            MedicalReportAnalysis.report_id == report.id
        )
    )

    if analysis is None or not analysis.findings_json:

        return extract_and_store(
            db,
            report,
        )

    return analysis


# =========================================================
# COMPATIBLE REPORT TYPE
# =========================================================

def is_compatible_type(
    previous: MedicalReportAnalysis,
    latest: MedicalReportAnalysis,
) -> bool:

    return (
        previous.report_type == "laboratory"
        and latest.report_type == "laboratory"
    )


# =========================================================
# AUTOMATIC PREVIOUS REPORT SEARCH
# =========================================================

def automatic_previous_comparison(
    db: Session,
    latest_report: MedicalReportUpload,
    latest_analysis: MedicalReportAnalysis,
) -> tuple[int | None, list[dict[str, Any]]]:

    if (
        latest_analysis.report_type != "laboratory"
        or not latest_analysis.findings_json
    ):

        return None, []

    previous_reports = db.scalars(
        select(MedicalReportUpload)
        .where(
            MedicalReportUpload.id != latest_report.id,
            or_(
                MedicalReportUpload.uploaded_at
                < latest_report.uploaded_at,

                and_(
                    MedicalReportUpload.uploaded_at
                    == latest_report.uploaded_at,

                    MedicalReportUpload.id
                    < latest_report.id,
                ),
            ),
        )
        .order_by(
            MedicalReportUpload.uploaded_at.desc(),
            MedicalReportUpload.id.desc(),
        )
        .limit(MAX_PREVIOUS_REPORTS_TO_CHECK)
    ).all()

    for previous_report in previous_reports:

        try:

            previous_analysis = get_or_extract(
                db,
                previous_report,
            )

            if not is_compatible_type(
                previous_analysis,
                latest_analysis,
            ):
                continue

            previous_id, comparisons = (
                compare_with_previous_report(
                    latest_analysis.findings_json or [],
                    [previous_analysis],
                )
            )

            if (
                previous_id is not None
                and any(
                    item.get("comparable")
                    for item in comparisons
                )
            ):

                return previous_id, comparisons

        except Exception as exc:

            db.rollback()

            logger.warning(
                "Skipping previous report %s: %s",
                previous_report.id,
                exc,
            )

            continue

    return None, []


# =========================================================
# API 1: ANALYZE ONE UPLOADED REPORT
# =========================================================

@router.post("/reports/{report_id}/analyze")
def analyze_uploaded_report(
    report_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:

    report = db.get(
        MedicalReportUpload,
        report_id,
    )

    if report is None:

        raise HTTPException(
            status_code=404,
            detail="Medical report not found.",
        )

    try:

        analysis = extract_and_store(
            db,
            report,
        )

        previous_id, comparisons = (
            automatic_previous_comparison(
                db,
                report,
                analysis,
            )
        )

        analysis.previous_report_id = previous_id

        analysis.comparison_json = comparisons

        analysis.summary = build_summary(
            analysis.report_type,
            analysis.findings_json or [],
            previous_id,
            comparisons,
            analysis.extraction_method,
        )

        ai_explanation = generate_ai_explanation(
            analysis.findings_json or [],
            comparisons,
        )

        analysis.analysis_status = "completed"

        analysis.created_at = ist_now()

        db.commit()

        db.refresh(analysis)

        return {
            "message": "Report analysis completed.",
            "analysis": analysis_to_dict(analysis),
            "ai_explanation": ai_explanation,
            "ai_explanation_status": (
                "generated"
                if ai_explanation
                else "not_configured_or_unavailable"
            ),
        }

    except HTTPException:

        db.rollback()
        raise

    except RuntimeError as exc:

        db.rollback()

        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except SQLAlchemyError as exc:

        db.rollback()

        logger.exception(
            "Database error during report analysis"
        )

        raise HTTPException(
            status_code=500,
            detail="Could not save report analysis.",
        ) from exc

    except Exception as exc:

        db.rollback()

        logger.exception(
            "Unexpected report analysis failure"
        )

        raise HTTPException(
            status_code=500,
            detail="Could not analyze report. Check server logs.",
        ) from exc


# =========================================================
# API 2: GET ANALYZED REPORT
# =========================================================

@router.get("/reports/{report_id}")
def get_report_analysis(
    report_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:

    analysis = db.scalar(
        select(MedicalReportAnalysis).where(
            MedicalReportAnalysis.report_id == report_id
        )
    )

    if analysis is None:

        raise HTTPException(
            status_code=404,
            detail="This report has not been analyzed yet.",
        )

    return {
        "analysis": analysis_to_dict(analysis)
    }


# =========================================================
# API 3: MANUAL REPORT COMPARISON
# =========================================================

@router.post("/compare")
def compare_selected_reports(
    request: CompareReportsRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:

    if (
        request.previous_report_id
        == request.latest_report_id
    ):

        raise HTTPException(
            status_code=400,
            detail="Select two different reports.",
        )

    previous_report = db.get(
        MedicalReportUpload,
        request.previous_report_id,
    )

    latest_report = db.get(
        MedicalReportUpload,
        request.latest_report_id,
    )

    if (
        previous_report is None
        or latest_report is None
    ):

        raise HTTPException(
            status_code=404,
            detail="One or both reports were not found.",
        )

    try:

        previous_analysis = get_or_extract(
            db,
            previous_report,
        )

        latest_analysis = get_or_extract(
            db,
            latest_report,
        )

        if not is_compatible_type(
            previous_analysis,
            latest_analysis,
        ):

            comparisons: list[dict[str, Any]] = []

            note = (
                "These are not both laboratory reports. "
                "They were analyzed separately. "
                "No numerical comparison was made."
            )

        else:

            _, comparisons = compare_with_previous_report(
                latest_analysis.findings_json or [],
                [previous_analysis],
            )

            note = (
                "Only matching test names and matching units "
                "are compared. Verify the original reports, "
                "test conditions and reference ranges."
            )

        has_comparable = any(
            item.get("comparable")
            for item in comparisons
        )

        latest_analysis.previous_report_id = (
            previous_report.id
            if has_comparable
            else None
        )

        latest_analysis.comparison_json = comparisons

        latest_analysis.summary = build_summary(
            latest_analysis.report_type,
            latest_analysis.findings_json or [],
            latest_analysis.previous_report_id,
            comparisons,
            latest_analysis.extraction_method,
        )

        latest_analysis.analysis_status = "completed"

        ai_explanation = generate_ai_explanation(
            latest_analysis.findings_json or [],
            comparisons,
        )

        db.commit()

        db.refresh(latest_analysis)

        return {
            "previous_report": {
                "id": previous_report.id,
                "filename": previous_report.original_filename,
                "uploaded_at": previous_report.uploaded_at.isoformat(
                    timespec="seconds"
                ),
            },

            "latest_report": {
                "id": latest_report.id,
                "filename": latest_report.original_filename,
                "uploaded_at": latest_report.uploaded_at.isoformat(
                    timespec="seconds"
                ),
            },

            "comparison_count": sum(
                1
                for item in comparisons
                if item.get("comparable")
            ),

            "comparisons": comparisons,

            "summary": latest_analysis.summary,

            "ai_explanation": ai_explanation,

            "ai_explanation_status": (
                "generated"
                if ai_explanation
                else "not_configured_or_unavailable"
            ),

            "note": note,
        }

    except HTTPException:

        db.rollback()
        raise

    except RuntimeError as exc:

        db.rollback()

        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except SQLAlchemyError as exc:

        db.rollback()

        logger.exception(
            "Database error during report comparison"
        )

        raise HTTPException(
            status_code=500,
            detail="Could not save report comparison.",
        ) from exc

    except Exception as exc:

        db.rollback()

        logger.exception(
            "Unexpected report comparison failure"
        )

        raise HTTPException(
            status_code=500,
            detail="Could not compare reports. Check server logs.",
        )
