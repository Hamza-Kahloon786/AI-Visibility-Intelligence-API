from app.api.errors import APIError
from app.extensions import db
from app.models.profile import BusinessProfile
from app.models.query import DiscoveredQuery


def get_profile_or_404(profile_uuid: str) -> BusinessProfile:
    profile = db.session.get(BusinessProfile, profile_uuid)
    if profile is None:
        raise APIError(
            f"Business profile '{profile_uuid}' not found.",
            status_code=404,
            code="profile_not_found",
        )
    return profile


def get_query_or_404(query_uuid: str) -> DiscoveredQuery:
    query = db.session.get(DiscoveredQuery, query_uuid)
    if query is None:
        raise APIError(
            f"Query '{query_uuid}' not found.",
            status_code=404,
            code="query_not_found",
        )
    return query
