from sqlalchemy import func

from app.extensions import db
from app.models.base import new_uuid, utcnow


class BusinessProfile(db.Model):
    __tablename__ = "business_profiles"

    uuid = db.Column(db.String(36), primary_key=True, default=new_uuid)
    name = db.Column(db.String(255), nullable=False)
    domain = db.Column(db.String(255), nullable=False, index=True)
    industry = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    competitors = db.Column(db.JSON, nullable=False, default=list)
    status = db.Column(db.String(32), nullable=False, default="created")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    pipeline_runs = db.relationship(
        "PipelineRun", backref="profile", lazy="dynamic", cascade="all, delete-orphan"
    )
    queries = db.relationship(
        "DiscoveredQuery", backref="profile", lazy="dynamic", cascade="all, delete-orphan"
    )
    recommendations = db.relationship(
        "ContentRecommendation",
        backref="profile",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "profile_uuid": self.uuid,
            "name": self.name,
            "domain": self.domain,
            "industry": self.industry,
            "description": self.description,
            "competitors": self.competitors or [],
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def summary_stats(self) -> dict:
        from app.models.query import DiscoveredQuery

        total_queries = self.queries.count()
        avg_score = self.queries.with_entities(
            func.avg(DiscoveredQuery.opportunity_score)
        ).scalar()
        scored_count = self.queries.filter(
            DiscoveredQuery.opportunity_score.isnot(None)
        ).count()
        not_visible_count = self.queries.filter_by(domain_visible=False).count()
        return {
            "total_queries_discovered": total_queries,
            "total_queries_scored": scored_count,
            "avg_opportunity_score": round(avg_score, 4) if avg_score is not None else None,
            "queries_missing_visibility": not_visible_count,
            "total_recommendations": self.recommendations.count(),
            "total_pipeline_runs": self.pipeline_runs.count(),
        }
