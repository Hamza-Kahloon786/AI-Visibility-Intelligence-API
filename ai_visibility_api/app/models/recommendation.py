from app.extensions import db
from app.models.base import new_uuid, utcnow

VALID_PRIORITIES = ("high", "medium", "low")
VALID_CONTENT_TYPES = ("blog_post", "landing_page", "faq", "comparison_page", "guide")


class ContentRecommendation(db.Model):
    __tablename__ = "content_recommendations"

    uuid = db.Column(db.String(36), primary_key=True, default=new_uuid)
    profile_uuid = db.Column(
        db.String(36), db.ForeignKey("business_profiles.uuid"), nullable=False, index=True
    )
    query_uuid = db.Column(
        db.String(36), db.ForeignKey("discovered_queries.uuid"), nullable=False, index=True
    )
    run_uuid = db.Column(
        db.String(36), db.ForeignKey("pipeline_runs.uuid"), nullable=True, index=True
    )

    content_type = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    rationale = db.Column(db.Text, nullable=False)
    target_keywords = db.Column(db.JSON, nullable=False, default=list)
    priority = db.Column(db.String(16), nullable=False, default="medium")

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "recommendation_uuid": self.uuid,
            "profile_uuid": self.profile_uuid,
            "target_query_uuid": self.query_uuid,
            "content_type": self.content_type,
            "title": self.title,
            "rationale": self.rationale,
            "target_keywords": self.target_keywords or [],
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
        }
