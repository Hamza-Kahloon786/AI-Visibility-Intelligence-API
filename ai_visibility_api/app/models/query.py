from app.extensions import db
from app.models.base import new_uuid, utcnow

VALID_INTENTS = ("comparison", "transactional", "informational", "navigational")


class DiscoveredQuery(db.Model):
    __tablename__ = "discovered_queries"

    uuid = db.Column(db.String(36), primary_key=True, default=new_uuid)
    profile_uuid = db.Column(
        db.String(36), db.ForeignKey("business_profiles.uuid"), nullable=False, index=True
    )
    run_uuid = db.Column(
        db.String(36), db.ForeignKey("pipeline_runs.uuid"), nullable=True, index=True
    )

    query_text = db.Column(db.Text, nullable=False)
    query_intent = db.Column(db.String(32), nullable=True)  # one of VALID_INTENTS

    estimated_search_volume = db.Column(db.Integer, nullable=True)
    competitive_difficulty = db.Column(db.Integer, nullable=True)  # 0-100
    opportunity_score = db.Column(db.Float, nullable=True)  # 0.0-1.0

    domain_visible = db.Column(db.Boolean, nullable=True)  # None = not yet scored
    visibility_position = db.Column(db.Integer, nullable=True)
    ai_answer_snippet = db.Column(db.Text, nullable=True)

    scoring_error = db.Column(db.Text, nullable=True)
    data_source = db.Column(db.String(32), nullable=True)  # "dataforseo" | "heuristic"

    discovered_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_checked_at = db.Column(db.DateTime(timezone=True), nullable=True)

    recommendations = db.relationship(
        "ContentRecommendation",
        # NOT "query" -- that would collide with Flask-SQLAlchemy's own
        # ContentRecommendation.query class attribute used for querying.
        backref="source_query",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    @property
    def visibility_status(self) -> str:
        if self.domain_visible is None:
            return "unknown"
        return "visible" if self.domain_visible else "not_visible"

    def to_dict(self) -> dict:
        return {
            "query_uuid": self.uuid,
            "profile_uuid": self.profile_uuid,
            "run_uuid": self.run_uuid,
            "query_text": self.query_text,
            "query_intent": self.query_intent,
            "estimated_search_volume": self.estimated_search_volume,
            "competitive_difficulty": self.competitive_difficulty,
            "opportunity_score": self.opportunity_score,
            "domain_visible": self.domain_visible,
            "visibility_position": self.visibility_position,
            "visibility_status": self.visibility_status,
            "data_source": self.data_source,
            "scoring_error": self.scoring_error,
            "discovered_at": self.discovered_at.isoformat(),
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
        }
