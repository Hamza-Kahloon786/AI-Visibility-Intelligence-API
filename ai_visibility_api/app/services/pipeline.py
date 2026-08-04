"""Orchestrates the 3-agent pipeline: Discovery -> Scoring -> Recommendation.

Failure isolation policy (see README "Agent architecture" section for the
full rationale):
- Agent 1 (discovery) already catches its own LLM failures and returns a
  degraded fallback query set internally, so the orchestrator only has a
  last-resort `except` around it for truly unexpected bugs -- if that
  triggers, the whole run is marked "failed" since there's nothing to score.
- Agent 2 (scoring) failures are isolated *per query* here: one bad query
  gets `scoring_error` recorded and is skipped; the rest of the batch still
  gets scored. This is the specific behaviour the assessment spec calls out.
- Agent 3 (recommendation) already catches its own LLM failures internally
  too; if something still escapes, the orchestrator treats it as "zero
  recommendations for this run" rather than failing queries that already
  scored successfully.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.agents.discovery import QueryDiscoveryAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.agents.scoring import VisibilityScoringAgent
from app.extensions import db
from app.models.base import utcnow
from app.models.pipeline_run import PipelineRun
from app.models.profile import BusinessProfile
from app.models.query import DiscoveredQuery
from app.models.recommendation import ContentRecommendation

logger = logging.getLogger(__name__)


@dataclass
class PipelineOutcome:
    run: PipelineRun
    queries: list[DiscoveredQuery] = field(default_factory=list)
    recommendations: list[ContentRecommendation] = field(default_factory=list)


class PipelineOrchestrator:
    def __init__(
        self,
        discovery_agent: QueryDiscoveryAgent,
        scoring_agent: VisibilityScoringAgent,
        recommendation_agent: ContentRecommendationAgent,
        max_discovery_queries: int = 18,
        max_gap_queries: int = 8,
    ):
        self.discovery_agent = discovery_agent
        self.scoring_agent = scoring_agent
        self.recommendation_agent = recommendation_agent
        self.max_discovery_queries = max_discovery_queries
        self.max_gap_queries = max_gap_queries

    def run(self, profile: BusinessProfile) -> PipelineOutcome:
        run = PipelineRun(profile_uuid=profile.uuid, status="running")
        db.session.add(run)
        db.session.commit()

        tokens_used = 0

        try:
            discovery_result = self.discovery_agent.run(profile)
        except Exception as exc:  # pragma: no cover - safety net, see module docstring
            logger.exception(
                "Unexpected QueryDiscoveryAgent failure for profile %s", profile.uuid
            )
            return self._fail_run(run, str(exc))

        tokens_used += discovery_result.tokens_used
        discovered = discovery_result.queries[: self.max_discovery_queries]

        query_rows = [
            DiscoveredQuery(
                profile_uuid=profile.uuid,
                run_uuid=run.uuid,
                query_text=item.query_text,
                query_intent=item.query_intent,
            )
            for item in discovered
        ]
        db.session.add_all(query_rows)
        db.session.flush()  # assign PKs/defaults without ending the transaction

        run.queries_discovered = len(query_rows)

        scored_count = 0
        for row in query_rows:
            try:
                scoring_result = self.scoring_agent.run(
                    query_text=row.query_text,
                    query_intent=row.query_intent,
                    profile=profile,
                )
            except Exception as exc:
                logger.warning(
                    "VisibilityScoringAgent failed for query %s (%r): %s",
                    row.uuid,
                    row.query_text,
                    exc,
                )
                row.scoring_error = str(exc)
                continue

            row.estimated_search_volume = scoring_result.estimated_search_volume
            row.competitive_difficulty = scoring_result.competitive_difficulty
            row.data_source = scoring_result.data_source
            row.domain_visible = scoring_result.domain_visible
            row.visibility_position = scoring_result.visibility_position
            row.ai_answer_snippet = scoring_result.ai_answer_snippet
            row.opportunity_score = scoring_result.opportunity_score
            tokens_used += scoring_result.tokens_used
            scored_count += 1

        run.queries_scored = scored_count
        db.session.flush()

        gap_queries = sorted(
            (q for q in query_rows if q.domain_visible is False),
            key=lambda q: q.opportunity_score or 0.0,
            reverse=True,
        )[: self.max_gap_queries]

        recommendation_rows: list[ContentRecommendation] = []
        try:
            recommendation_result = self.recommendation_agent.run(gap_queries, profile)
            tokens_used += recommendation_result.tokens_used
            for item in recommendation_result.items:
                rec = ContentRecommendation(
                    profile_uuid=profile.uuid,
                    query_uuid=item.query_uuid,
                    run_uuid=run.uuid,
                    content_type=item.content_type,
                    title=item.title,
                    rationale=item.rationale,
                    target_keywords=item.target_keywords,
                    priority=item.priority,
                )
                db.session.add(rec)
                recommendation_rows.append(rec)
        except Exception:  # pragma: no cover - safety net, see module docstring
            logger.exception(
                "Unexpected ContentRecommendationAgent failure for profile %s; "
                "run will complete with zero recommendations.",
                profile.uuid,
            )

        run.recommendations_generated = len(recommendation_rows)
        run.tokens_used = tokens_used
        run.status = "completed"
        run.completed_at = utcnow()
        profile.status = "analyzed"

        db.session.commit()

        return PipelineOutcome(
            run=run, queries=query_rows, recommendations=recommendation_rows
        )

    @staticmethod
    def _fail_run(run: PipelineRun, error_message: str) -> PipelineOutcome:
        run.status = "failed"
        run.error_message = error_message
        run.completed_at = utcnow()
        db.session.commit()
        return PipelineOutcome(run=run)
