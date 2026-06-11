"""
Cint Survey Cold-Start AI Scoring Task
=======================================

When a new Cint survey arrives via the opportunities webhook with no
in-field data (conversion == 0, bid_incidence == 0), this task uses
Claude to predict a conversion score from survey metadata.

The score is written to cint_surveys.predicted_score and is used as
the last-resort fallback in the country-wise ranking when no real IR
data exists.

Per Cint's Yield Management guide recommendation:
  "apply a machine learning approach and train your system on what are
   the main characteristics and data patterns behind good converting
   surveys, by each buyer."
"""

import os
import json
import logging
from typing import Any, Dict

from celery_app import celery_app

logger = logging.getLogger(__name__)

# Minimum session threshold before we rely on real data (Cint guide: 20)
INTERNAL_IR_MIN_SESSIONS = 20

# Claude model — lightweight, keeps token cost low for this high-volume task
_AI_MODEL = "claude-haiku-4-5"

# System prompt — concise so it stays within the cheap model's sweet spot
_SYSTEM_PROMPT = (
    "You are a survey-industry conversion analyst. "
    "Given survey metadata, predict what percentage of respondents who reach "
    "the survey (after the Cint Exchange prescreener) will complete it. "
    "Output ONLY a JSON object: "
    '{\"predicted_score\": <float 0-100>, \"confidence\": \"low\"|\"medium\"|\"high\", \"reasoning\": \"<one sentence>\"}. '
    "Do not include any other text."
)


def _build_prompt(survey: Dict[str, Any]) -> str:
    """Build the user-facing prompt from survey fields."""
    parts = [
        f"study_type: {survey.get('study_type', 'unknown')}",
        f"buyer: {survey.get('account_name', 'unknown')}",
        f"country_language: {survey.get('country_language', 'unknown')}",
        f"estimated_IR_percent: {survey.get('bid_incidence', 0)}",
        f"estimated_LOI_minutes: {survey.get('bid_length_of_interview', 0)}",
        f"revenue_per_interview_usd: {survey.get('payout', 0)}",
        f"collects_pii: {survey.get('collects_pii', False)}",
        f"relationship_type: {survey.get('relationship_type', 'open')}",
    ]
    return "Survey metadata:\n" + "\n".join(parts)


@celery_app.task(
    bind=True,
    name="backend.tasks.cint_survey_scoring.score_cold_start_survey",
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    rate_limit="30/m",  # gpt-4o-mini rate headroom
    ignore_result=False,
    queue="default",
)
def score_cold_start_survey(self, survey_id: int) -> Dict[str, Any]:
    """
    Predict conversion score for a cold-start Cint survey.

    Args:
        survey_id: Cint survey_id integer

    Returns:
        {
            "survey_id": int,
            "predicted_score": float,   # 0-100 scale
            "confidence": str,
            "reasoning": str,
            "skipped": bool             # True if survey already has real data
        }
    """
    from database import get_client  # noqa: import inside task to avoid circular

    task_id = self.request.id
    client = get_client()
    surveys_col = client["cint_research"]["cint_surveys"]

    survey = surveys_col.find_one({"survey_id": survey_id})
    if not survey:
        logger.warning(f"[CintScoring] survey_id={survey_id} not found in DB")
        return {"survey_id": survey_id, "skipped": True, "reason": "not_found"}

    # Skip if real conversion data already present
    conversion = float(survey.get("conversion") or 0)
    bid_incidence = float(survey.get("bid_incidence") or 0)
    if conversion > 0 or bid_incidence > 0:
        logger.info(f"[CintScoring] survey_id={survey_id} has real data, skipping AI score")
        return {"survey_id": survey_id, "skipped": True, "reason": "has_real_data"}

    try:
        from ai_governance.claude_gateway import ClaudeChatClient

        oai = ClaudeChatClient()  # governed Claude client (key resolved by ai_governance)
        prompt = _build_prompt(survey)

        response = oai.chat.completions.create(
            model=_AI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=120,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        parsed = json.loads(raw)

        predicted_score = float(parsed.get("predicted_score", 0))
        confidence = str(parsed.get("confidence", "low"))
        reasoning = str(parsed.get("reasoning", ""))

        # Clamp to 0-100
        predicted_score = max(0.0, min(100.0, predicted_score))

        surveys_col.update_one(
            {"survey_id": survey_id},
            {"$set": {
                "predicted_score": predicted_score,
                "predicted_score_confidence": confidence,
                "predicted_score_reasoning": reasoning,
                "predicted_score_task_id": task_id,
            }},
        )

        logger.info(
            f"[CintScoring] survey_id={survey_id} score={predicted_score:.1f} "
            f"confidence={confidence}"
        )
        return {
            "survey_id": survey_id,
            "predicted_score": predicted_score,
            "confidence": confidence,
            "reasoning": reasoning,
            "skipped": False,
        }

    except Exception as exc:
        logger.error(f"[CintScoring] survey_id={survey_id} failed: {exc}")
        raise
