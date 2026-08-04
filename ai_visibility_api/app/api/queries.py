from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from app.api.errors import APIError
from app.api.helpers import get_query_or_404
from app.extensions import db
from app.models.base import utcnow
from app.models.profile import BusinessProfile

queries_bp = Blueprint("queries", __name__, url_prefix="/api/v1/queries")


@queries_bp.post("/<query_uuid>/recheck")
def recheck_query(query_uuid: str):
    query_row = get_query_or_404(query_uuid)
    profile = db.session.get(BusinessProfile, query_row.profile_uuid)

    scoring_agent = current_app.pipeline_orchestrator.scoring_agent
    try:
        result = scoring_agent.run(
            query_text=query_row.query_text,
            query_intent=query_row.query_intent,
            profile=profile,
        )
    except Exception as exc:
        query_row.scoring_error = str(exc)
        query_row.last_checked_at = utcnow()
        db.session.commit()
        raise APIError(
            f"Visibility recheck failed: {exc}", status_code=502, code="recheck_failed"
        ) from exc

    query_row.estimated_search_volume = result.estimated_search_volume
    query_row.competitive_difficulty = result.competitive_difficulty
    query_row.data_source = result.data_source
    query_row.domain_visible = result.domain_visible
    query_row.visibility_position = result.visibility_position
    query_row.ai_answer_snippet = result.ai_answer_snippet
    query_row.opportunity_score = result.opportunity_score
    query_row.scoring_error = None
    query_row.last_checked_at = utcnow()
    db.session.commit()

    return jsonify(query_row.to_dict()), 200
