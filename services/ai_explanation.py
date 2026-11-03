
"""
AI explanation service using Ollama.

Purpose:
1. Explain extracted medical laboratory results.
2. Explain changes between previous and latest reports.
3. Generate simple English explanations.
4. Keep AI explanations optional if Ollama is unavailable.

This module does not diagnose diseases or prescribe medication.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

# Load environment variables from the project's .env file.
load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

DEFAULT_OLLAMA_MODEL = "gpt-oss:120b-cloud"

DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------
# AI EXPLANATION FUNCTION
# ---------------------------------------------------------

def generate_ai_explanation(
    latest_findings: list[dict[str, Any]],
    comparisons: list[dict[str, Any]] | None = None,
) -> str | None:
    """
    Generate a patient-friendly explanation using Ollama.

    Args:
        latest_findings:
            Extracted laboratory findings from the latest report.

        comparisons:
            Matching laboratory results from previous reports.

    Returns:
        AI-generated explanation as a string.
        Returns None if Ollama is unavailable or generation fails.
    """

    # -----------------------------------------------------
    # 1. READ OLLAMA CONFIGURATION
    # -----------------------------------------------------

    model = os.getenv(
        "OLLAMA_MODEL",
        DEFAULT_OLLAMA_MODEL,
    ).strip()

    base_url = os.getenv(
        "OLLAMA_BASE_URL",
        DEFAULT_OLLAMA_URL,
    ).strip().rstrip("/")

    timeout_value = os.getenv(
        "OLLAMA_TIMEOUT_SECONDS",
        str(DEFAULT_TIMEOUT),
    )

    try:
        timeout = float(timeout_value)

        if timeout <= 0:
            raise ValueError("Timeout must be greater than zero.")

    except ValueError:
        logger.warning(
            "Invalid OLLAMA_TIMEOUT_SECONDS. Using default timeout."
        )
        timeout = DEFAULT_TIMEOUT

    if not model:
        logger.warning(
            "OLLAMA_MODEL is not configured."
        )
        return None

    # -----------------------------------------------------
    # 2. CHECK INPUT DATA
    # -----------------------------------------------------

    if not isinstance(latest_findings, list):
        logger.warning(
            "Latest findings must be a list."
        )
        return None

    if not latest_findings:
        return (
            "No supported laboratory results were extracted "
            "from the uploaded report. Please check the original "
            "medical report."
        )

    if comparisons is None:
        comparisons = []

    if not isinstance(comparisons, list):
        logger.warning(
            "Comparisons must be a list."
        )
        return None

    # -----------------------------------------------------
    # 3. PREPARE MEDICAL DATA
    # -----------------------------------------------------

    medical_data = {
        "latest_report_findings": latest_findings,
        "previous_report_comparisons": comparisons,
    }

    try:
        medical_json = json.dumps(
            medical_data,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    except (TypeError, ValueError):
        logger.exception(
            "Could not convert medical data into JSON."
        )
        return None

    # -----------------------------------------------------
    # 4. CREATE AI PROMPT
    # -----------------------------------------------------

    prompt = f"""
You are an AI medical laboratory report explanation assistant.

Your task is to explain medical laboratory report information
in simple, understandable English.

Use ONLY the structured medical data supplied below.

YOUR TASKS:

1. Explain the extracted laboratory test names.
2. Explain the numerical test results.
3. Explain LOW, HIGH and WITHIN_RANGE statuses when provided.
4. Explain reference ranges only when they are available.
5. Explain which values increased, decreased or remained unchanged.
6. Explain comparisons with previous laboratory reports.
7. Mention when previous report values are unavailable.
8. Mention when results cannot safely be compared.
9. Help the patient understand what questions they can ask their doctor.

IMPORTANT MEDICAL SAFETY RULES:

1. Do not diagnose any disease.
2. Do not prescribe medicines.
3. Do not recommend changing prescribed medication.
4. Do not invent missing test values.
5. Do not invent reference ranges.
6. Do not say that an increase or decrease is automatically good or bad.
7. Explain that medical interpretation depends on patient history,
   age, clinical symptoms, test conditions and laboratory methods.
8. Explain that extracted values must be verified against the original
   medical report.
9. Recommend discussing abnormal or concerning results with a
   qualified healthcare professional.
10. Do not present this explanation as a doctor's medical diagnosis.

RESPONSE FORMAT:

Use the following headings:

1. Report Overview
2. Extracted Test Results
3. Previous Report Comparison
4. Important Observations
5. Suggested Next Steps

Keep the explanation below 150 words.
Use simple English.

MEDICAL DATA:

{medical_json}
"""

    # -----------------------------------------------------
    # 5. PREPARE OLLAMA API REQUEST
    # -----------------------------------------------------

    api_url = f"{base_url}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }

    # -----------------------------------------------------
    # 6. SEND REQUEST TO OLLAMA
    # -----------------------------------------------------

    try:

        with httpx.Client(
            timeout=timeout,
        ) as client:

            response = client.post(
                api_url,
                json=payload,
            )

            response.raise_for_status()

            result = response.json()

        # -------------------------------------------------
        # 7. EXTRACT AI RESPONSE
        # -------------------------------------------------

        explanation = str(
            result.get("response", "")
        ).strip()

        if not explanation:

            logger.warning(
                "Ollama returned an empty AI explanation."
            )

            return None

        logger.info(
            "AI medical report explanation generated successfully."
        )

        return explanation[:4000]

    # -----------------------------------------------------
    # 8. ERROR HANDLING
    # -----------------------------------------------------

    except httpx.TimeoutException:

        logger.warning(
            "Ollama request timed out after %s seconds.",
            timeout,
        )

        return None

    except httpx.HTTPStatusError as exc:

        logger.error(
            "Ollama HTTP error: %s",
            exc.response.status_code,
        )

        return None

    except httpx.RequestError:

        logger.exception(
            "Unable to connect to Ollama at %s.",
            base_url,
        )

        return None

    except (ValueError, TypeError):

        logger.exception(
            "Could not process the Ollama response."
        )

        return None

    except Exception:

        logger.exception(
            "Unexpected error while generating AI explanation."
        )

        return None
