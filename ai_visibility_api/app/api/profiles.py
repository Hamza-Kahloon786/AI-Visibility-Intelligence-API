from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.api.errors import APIError
from app.api.helpers import get_profile_or_404
from app.extensions import db, limiter
from app.models.profile import BusinessProfile
from app.models.query import DiscoveredQuery
from app.models.recommendation import ContentRecommendation
from app.schemas.profile_schema import ProfileCreateRequest

profiles_bp = Blueprint("profiles", __name__, url_prefix="/api/v1/profiles")

_VALID_VISIBILITY_STATUSES = ("visible", "not_visible", "unknown")


@profiles_bp.post("")
def create_profile():
    payload = request.get_json(silent=True)
    if payload is None:
        raise APIError(
            "Request body must be valid JSON.", status_code=400, code="invalid_json"
        )

    data = ProfileCreateRequest.model_validate(payload)

    profile = BusinessProfile(
        name=data.name,
        domain=data.domain,
        industry=data.industry,
        description=data.description,
        competitors=data.competitors,
        status="created",
    )
    db.session.add(profile)
    db.session.commit()

    return jsonify(profile.to_dict()), 201


@profiles_bp.get("/<profile_uuid>")
def get_profile(profile_uuid: str):
    profile = get_profile_or_404(profile_uuid)
    body = profile.to_dict()
    body["stats"] = profile.summary_stats()
    return jsonify(body), 200


@profiles_bp.post("/<profile_uuid>/run")
@limiter.limit(lambda: current_app.config["PIPELINE_RUN_RATE_LIMIT"])
def run_pipeline(profile_uuid: str):
    profile = get_profile_or_404(profile_uuid)

    orchestrator = current_app.pipeline_orchestrator
    outcome = orchestrator.run(profile)
    run = outcome.run

    top_queries = sorted(
        outcome.queries, key=lambda q: q.opportunity_score or 0.0, reverse=True
    )[:3]

    return (
        jsonify(
            {
                "pipeline_run_uuid": run.uuid,
                "profile_uuid": profile.uuid,
                "status": run.status,
                "error_message": run.error_message,
                "queries_discovered": run.queries_discovered,
                "queries_scored": run.queries_scored,
                "top_opportunity_queries": [q.to_dict() for q in top_queries],
                "content_recommendations": [r.to_dict() for r in outcome.recommendations],
                "tokens_used": run.tokens_used,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            }
        ),
        201,
    )


@profiles_bp.get("/<profile_uuid>/queries")
def list_queries(profile_uuid: str):
    profile = get_profile_or_404(profile_uuid)
    query = DiscoveredQuery.query.filter_by(profile_uuid=profile.uuid)

    min_score = request.args.get("min_score", type=float)
    if min_score is not None:
        query = query.filter(DiscoveredQuery.opportunity_score >= min_score)

    status = request.args.get("status")
    if status is not None:
        if status not in _VALID_VISIBILITY_STATUSES:
            raise APIError(
                f"status must be one of: {', '.join(_VALID_VISIBILITY_STATUSES)}.",
                status_code=400,
                code="invalid_query_param",
            )
        if status == "visible":
            query = query.filter(DiscoveredQuery.domain_visible.is_(True))
        elif status == "not_visible":
            query = query.filter(DiscoveredQuery.domain_visible.is_(False))
        else:
            query = query.filter(DiscoveredQuery.domain_visible.is_(None))

    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=20, type=int)
    if page is None or page < 1:
        raise APIError("page must be >= 1.", status_code=400, code="invalid_pagination")
    if per_page is None or not (1 <= per_page <= 100):
        raise APIError(
            "per_page must be between 1 and 100.", status_code=400, code="invalid_pagination"
        )

    query = query.order_by(DiscoveredQuery.opportunity_score.desc().nullslast())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return (
        jsonify(
            {
                "profile_uuid": profile.uuid,
                "page": page,
                "per_page": per_page,
                "total": pagination.total,
                "total_pages": pagination.pages,
                "queries": [q.to_dict() for q in pagination.items],
            }
        ),
        200,
    )


@profiles_bp.get("/<profile_uuid>/recommendations")
def list_recommendations(profile_uuid: str):
    profile = get_profile_or_404(profile_uuid)
    recommendations = (
        ContentRecommendation.query.filter_by(profile_uuid=profile.uuid)
        .order_by(ContentRecommendation.created_at.desc())
        .all()
    )
    return (
        jsonify(
            {
                "profile_uuid": profile.uuid,
                "recommendations": [r.to_dict() for r in recommendations],
            }
        ),
        200,
    )
