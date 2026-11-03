
"""Medical report PDF/OCR extraction and comparison."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


# =========================================================
# SUPPORTED LABORATORY TESTS
# =========================================================

TEST_ALIASES: dict[str, tuple[str, ...]] = {
    "Hemoglobin": (
        "hemoglobin",
        "haemoglobin",
        "hgb",
        "hb",
    ),
    "WBC": (
        "white blood cell count",
        "total leukocyte count",
        "wbc",
        "tlc",
    ),
    "RBC": (
        "red blood cell count",
        "rbc",
    ),
    "Platelets": (
        "platelet count",
        "platelets",
        "platelet",
    ),
    "Hematocrit": (
        "hematocrit",
        "haematocrit",
        "hct",
        "pcv",
    ),
    "Neutrophils": (
        "neutrophils",
        "neutrophil",
    ),
    "Lymphocytes": (
        "lymphocytes",
        "lymphocyte",
    ),
    "ESR": (
        "erythrocyte sedimentation rate",
        "esr",
    ),
    "CRP": (
        "c-reactive protein",
        "c reactive protein",
        "crp",
    ),
    "Glucose": (
        "fasting blood glucose",
        "fasting blood sugar",
        "blood glucose",
        "glucose",
        "fbs",
        "rbs",
    ),
    "HbA1c": (
        "glycated hemoglobin",
        "glycosylated hemoglobin",
        "hba1c",
        "a1c",
    ),
    "Total Cholesterol": (
        "total cholesterol",
        "cholesterol",
    ),
    "LDL": (
        "low density lipoprotein",
        "ldl cholesterol",
        "ldl",
    ),
    "HDL": (
        "high density lipoprotein",
        "hdl cholesterol",
        "hdl",
    ),
    "Triglycerides": (
        "triglycerides",
        "triglyceride",
        "tg",
    ),
    "Creatinine": (
        "serum creatinine",
        "creatinine",
    ),
    "Urea": (
        "blood urea nitrogen",
        "bun",
        "urea",
    ),
    "TSH": (
        "thyroid stimulating hormone",
        "tsh",
    ),
}


# =========================================================
# REGULAR EXPRESSIONS
# =========================================================

VALUE_RE = re.compile(
    r"(?P<qualifier>[<>≤≥])?\s*"
    r"(?P<value>\d[\d,]*(?:\.\d+)?)"
)

RANGE_RE = re.compile(
    r"(?P<low>\d[\d,]*(?:\.\d+)?)"
    r"\s*(?:-|–|—|\bto\b)\s*"
    r"(?P<high>\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)

UNIT_RE = re.compile(
    r"(?<![a-z])"
    r"(?:"
    r"mg/dl|mg/l|g/dl|g/l|mmol/l|"
    r"µmol/l|umol/l|ng/ml|pg/ml|"
    r"miu/l|iu/l|u/l|cells/ul|"
    r"10\^?3/?ul|10\^?6/?ul|"
    r"10\*?3/?ul|10\*?6/?ul|"
    r"fl|pg|%"
    r")"
    r"(?![a-z])",
    re.IGNORECASE,
)


# =========================================================
# NUMBER CONVERSION
# =========================================================

def number(raw: str) -> float | None:
    """Convert report numbers into a Python float."""

    value = raw.strip().replace(" ", "")

    if value.startswith(("<", ">", "≤", "≥")):
        value = value[1:]

    if "," in value and "." not in value:
        tail = value.rsplit(",", 1)[-1]

        if len(tail) == 3:
            value = value.replace(",", "")
        else:
            value = value.replace(",", ".")

    else:
        value = value.replace(",", "")

    try:
        return float(value)

    except ValueError:
        return None


def normalize_unit(
    unit: str | None,
) -> str:
    """Normalize a unit without performing unsafe conversions."""

    if not unit:
        return ""

    unit = unit.lower().strip()

    unit = unit.replace("μ", "µ")
    unit = unit.replace(" ", "")
    unit = unit.replace("microlitre", "ul")

    return unit


# =========================================================
# EXTRACT LABORATORY FINDINGS
# =========================================================

def extract_lab_findings(
    text: str,
) -> list[dict[str, Any]]:
    """Extract supported laboratory values from report text.

    This is a rule-based prototype. It does not understand every
    possible laboratory report layout.
    """

    findings: dict[str, dict[str, Any]] = {}

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    aliases: list[tuple[str, str]] = []

    for canonical, names in TEST_ALIASES.items():
        for name in names:
            aliases.append((name, canonical))

    # Check longer test names first.
    aliases.sort(
        key=lambda item: len(item[0]),
        reverse=True,
    )

    for index, line in enumerate(lines):

        # Some reports place the value on the next line.
        candidates = [line]

        if index + 1 < len(lines):
            candidates.append(
                line + " " + lines[index + 1]
            )

        for candidate in candidates:

            matched = False

            for alias, canonical in aliases:

                pattern = re.compile(
                    r"(?<![a-z0-9])"
                    + re.escape(alias)
                    + r"(?![a-z0-9])",
                    re.IGNORECASE,
                )

                alias_match = pattern.search(candidate)

                if not alias_match:
                    continue

                remainder = candidate[alias_match.end():]

                value_match = VALUE_RE.search(remainder)

                if not value_match:
                    continue

                extracted_value = number(
                    value_match.group("value")
                )

                if extracted_value is None:
                    continue

                qualifier = (
                    value_match.group("qualifier")
                    or None
                )

                # Identify unit from the whole result line.
                unit_match = UNIT_RE.search(candidate)

                unit = normalize_unit(
                    unit_match.group(0)
                    if unit_match
                    else None
                )

                # Identify a stated reference range.
                reference_range = None

                range_match = RANGE_RE.search(
                    candidate,
                    alias_match.end(),
                )

                if range_match:

                    low = number(
                        range_match.group("low")
                    )

                    high = number(
                        range_match.group("high")
                    )

                    if (
                        low is not None
                        and high is not None
                        and low <= high
                    ):

                        reference_range = {
                            "low": low,
                            "high": high,
                        }

                findings[canonical] = {
                    "test": canonical,
                    "value": extracted_value,
                    "unit": unit,
                    "qualifier": qualifier,
                    "reference_range": reference_range,
                    "source_line": candidate[:500],
                }

                matched = True
                break

            if matched:
                break

    return list(findings.values())


# =========================================================
# REPORT CLASSIFICATION
# =========================================================

def classify_report(
    title: str,
    filename: str,
    text: str,
    findings: list[dict[str, Any]],
) -> str:

    combined = (
        f"{title} {filename} {text[:12000]}"
    ).lower()

    if findings:
        return "laboratory"

    imaging_terms = (
        "x-ray",
        "xray",
        "radiograph",
        "radiology",
        "mri",
        "ct scan",
        "fracture",
        "impression",
        "ultrasound",
    )

    if any(
        term in combined
        for term in imaging_terms
    ):
        return "radiology_or_imaging"

    ecg_terms = (
        "ecg",
        "ekg",
        "electrocardiogram",
    )

    if any(
        term in combined
        for term in ecg_terms
    ):
        return "ecg"

    return "other"


# =========================================================
# PDF TEXT EXTRACTION
# =========================================================

def extract_pdf_text(
    path: Path,
) -> tuple[str, str]:

    try:
        import pymupdf

    except ImportError as exc:

        raise RuntimeError(
            "PyMuPDF is not installed. "
            "Run: pip install PyMuPDF"
        ) from exc

    text_parts: list[str] = []

    with pymupdf.open(path) as document:

        for page in document:

            text_parts.append(
                page.get_text("text")
            )

        text = "\n".join(
            text_parts
        ).strip()

        # Text-based PDF.
        if len(text) >= 40:

            return text, "pdf_text"

        # Scanned PDF: try OCR.
        try:

            from PIL import Image
            import pytesseract

        except ImportError:

            return text, "pdf_text_no_ocr"

        tesseract_cmd = os.getenv(
            "TESSERACT_CMD"
        )

        if tesseract_cmd:

            pytesseract.pytesseract.tesseract_cmd = (
                tesseract_cmd
            )

        ocr_parts: list[str] = []

        for page in document:

            pixmap = page.get_pixmap(
                dpi=220,
                alpha=False,
            )

            image = Image.frombytes(
                "RGB",
                (pixmap.width, pixmap.height),
                pixmap.samples,
            )

            try:

                page_text = (
                    pytesseract.image_to_string(
                        image,
                        config="--psm 6",
                    )
                )

                ocr_parts.append(page_text)

            except (
                pytesseract.TesseractNotFoundError,
            ):

                return text, "pdf_text_no_ocr"

        ocr_text = "\n".join(
            ocr_parts
        ).strip()

        if ocr_text:

            return ocr_text, "pdf_ocr"

        return text, "pdf_text_no_ocr"


# =========================================================
# IMAGE OCR
# =========================================================

def extract_image_text(
    path: Path,
) -> tuple[str, str]:

    try:

        from PIL import Image
        import pytesseract

    except ImportError as exc:

        raise RuntimeError(
            "Pillow and pytesseract are required for image OCR."
        ) from exc

    tesseract_cmd = os.getenv(
        "TESSERACT_CMD"
    )

    if tesseract_cmd:

        pytesseract.pytesseract.tesseract_cmd = (
            tesseract_cmd
        )

    with Image.open(path) as image:

        try:

            image = image.convert("RGB")

            extracted_text = (
                pytesseract.image_to_string(
                    image,
                    config="--psm 6",
                )
            )

            return extracted_text, "image_ocr"

        except pytesseract.TesseractNotFoundError as exc:

            raise RuntimeError(
                "Tesseract OCR is not installed or "
                "not available in PATH."
            ) from exc


# =========================================================
# EXTRACT TEXT FROM SUPPORTED REPORT
# =========================================================

def extract_report_text(
    path: Path,
    content_type: str,
) -> tuple[str, str]:

    extension = path.suffix.lower()

    if (
        content_type == "application/pdf"
        or extension == ".pdf"
    ):

        return extract_pdf_text(path)

    if (
        content_type.startswith("image/")
        or extension in {".png", ".jpg", ".jpeg"}
    ):

        return extract_image_text(path)

    raise RuntimeError(
        "Unsupported medical report format."
    )


# =========================================================
# REFERENCE RANGE STATUS
# =========================================================

def range_status(
    value: float,
    reference_range: dict[str, float] | None,
) -> str:

    if not reference_range:

        return "reference_range_unavailable"

    low = reference_range.get("low")
    high = reference_range.get("high")

    if low is not None and value < low:

        return "below_reported_range"

    if high is not None and value > high:

        return "above_reported_range"

    return "within_reported_range"


# =========================================================
# COMPARE TWO FINDINGS
# =========================================================

def compare_findings(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
) -> list[dict[str, Any]]:

    previous_by_test = {
        item.get("test"): item
        for item in previous
        if item.get("test")
    }

    comparisons: list[dict[str, Any]] = []

    for item in current:

        old = previous_by_test.get(
            item.get("test")
        )

        if not old:
            continue

        current_unit = normalize_unit(
            item.get("unit")
        )

        old_unit = normalize_unit(
            old.get("unit")
        )

        # Do not compare qualified values.
        if (
            item.get("qualifier")
            or old.get("qualifier")
        ):

            comparisons.append({
                "test": item["test"],
                "comparable": False,
                "reason": (
                    "A result contains a less-than or "
                    "greater-than qualifier. Exact values "
                    "cannot be compared."
                ),
            })

            continue

        # Units must be present and identical.
        if (
            not current_unit
            or not old_unit
            or current_unit != old_unit
        ):

            comparisons.append({
                "test": item["test"],
                "comparable": False,
                "reason": (
                    "Units are missing or different. "
                    "Values were not compared."
                ),
                "previous_unit": old.get("unit"),
                "latest_unit": item.get("unit"),
            })

            continue

        old_value = float(
            old["value"]
        )

        new_value = float(
            item["value"]
        )

        difference = (
            new_value - old_value
        )

        if difference > 0:

            direction = "increased"

        elif difference < 0:

            direction = "decreased"

        else:

            direction = "unchanged"

        percent_change = (
            round(
                (difference / old_value) * 100,
                2,
            )
            if old_value != 0
            else None
        )

        comparisons.append({
            "test": item["test"],
            "comparable": True,
            "previous_value": old_value,
            "latest_value": new_value,
            "unit": current_unit,
            "difference": round(difference, 4),
            "percent_change": percent_change,
            "direction": direction,

            "previous_reference_range": (
                old.get("reference_range")
            ),

            "latest_reference_range": (
                item.get("reference_range")
            ),

            "previous_range_status": range_status(
                old_value,
                old.get("reference_range"),
            ),

            "latest_range_status": range_status(
                new_value,
                item.get("reference_range"),
            ),
        })

    return comparisons


# =========================================================
# FIND COMPATIBLE PREVIOUS REPORT
# =========================================================

def compare_with_previous_report(
    current_findings: list[dict[str, Any]],
    previous_analyses: list[Any],
) -> tuple[int | None, list[dict[str, Any]]]:

    if not current_findings:

        return None, []

    for previous in previous_analyses:

        previous_findings = (
            previous.findings_json or []
        )

        comparisons = compare_findings(
            current_findings,
            previous_findings,
        )

        if any(
            item.get("comparable")
            for item in comparisons
        ):

            return (
                previous.report_id,
                comparisons,
            )

    return None, []


# =========================================================
# BUILD SUMMARY
# =========================================================

def build_summary(
    report_type: str,
    findings: list[dict[str, Any]],
    previous_report_id: int | None,
    comparisons: list[dict[str, Any]],
    extraction_method: str,
) -> str:

    if (
        extraction_method.endswith("no_ocr")
        or not findings
    ):

        if report_type == "radiology_or_imaging":

            return (
                "This appears to be a radiology or imaging "
                "report. The original file was saved, but "
                "this module does not interpret X-ray, MRI "
                "or CT image pixels. Written radiologist "
                "findings may be extracted when readable."
            )

        return (
            "The report was saved, but no supported "
            "numerical laboratory values were reliably "
            "extracted. Please verify the original report. "
            "Scanned or complex layouts may require OCR "
            "review or manual correction."
        )

    comparable = [
        item
        for item in comparisons
        if item.get("comparable")
    ]

    if comparable:

        parts = [
            f"Extracted {len(findings)} supported "
            f"laboratory marker(s). Compared "
            f"{len(comparable)} matching marker(s) "
            f"with previous report #{previous_report_id}."
        ]

        for item in comparable:

            parts.append(
                f"{item['test']}: "
                f"{item['previous_value']} -> "
                f"{item['latest_value']} "
                f"{item['unit']} "
                f"({item['direction']}, "
                f"difference {item['difference']})."
            )

        return " ".join(parts)

    return (
        f"Extracted {len(findings)} supported laboratory "
        "marker(s). No previous report with matching "
        "test names and identical units was found. "
        "No numerical comparison was made."
    )


# =========================================================
# COMPLETE REPORT ANALYSIS
# =========================================================

def analyze_report_file(
    path: Path,
    content_type: str,
    title: str,
    filename: str,
) -> dict[str, Any]:

    text, method = extract_report_text(
        path,
        content_type,
    )

    findings = extract_lab_findings(
        text
    )

    report_type = classify_report(
        title,
        filename,
        text,
        findings,
    )

    return {
        "report_type": report_type,
        "extraction_method": method,
        "extracted_text": text[:100000],
        "findings": findings,
    }
