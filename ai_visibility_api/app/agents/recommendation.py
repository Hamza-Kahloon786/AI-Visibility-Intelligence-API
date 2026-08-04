"""Agent 3 -- Content Recommendation.

Given the top opportunity-score queries where the target domain is NOT
appearing, generates specific, actionable content recommendations.

Reference-key design: rather than asking the LLM to echo back full query
text (fragile to match against the DB afterwards) or a UUID (LLMs mangle
long IDs), each gap query is given a short "Q1", "Q2", ... label in the
prompt. The model is instructed to respond with that label, which is then
looked up in a local dict to recover the real `query_uuid` deterministically
-- no fuzzy string matching involved.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agents.base import BaseAgent
from app.models.profile import BusinessProfile
from app.models.query import DiscoveredQuery
from app.schemas.agent_io import RecommendationOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Content Recommendation Agent inside an AI-visibility \
analytics platform.

You will be given a target business and a list of "gap queries": real questions \
users ask AI assistants in this business's competitive space, where the target \
domain currently does NOT appear in the simulated AI-generated answer. Each gap \
query has a reference label (Q1, Q2, ...), its estimated search volume, \
competitive difficulty, and opportunity score.

Your job: generate 3-5 specific, actionable content recommendations that would \
close these visibility gaps. Each recommendation must:
- Target ONE gap query by its reference label (target_query_ref, e.g. "Q1").
- Prioritise the highest opportunity-score queries first, but you may combine \
closely related queries under one piece of content only if you still pick a \
single representative target_query_ref for it.
- State a specific, publishable content title (not "write a blog post about X").
- Explain, in the rationale, specifically why this content closes the gap for \
that query -- reference the query's actual topic and intent, not generic SEO \
advice.
- List concrete target keywords/topics the content should cover (not the query \
text verbatim restated).
- Assign a content_type: "blog_post", "landing_page", "faq", "comparison_page", \
or "guide" -- pick the type that best matches the query's intent (e.g. \
comparison-intent queries usually warrant a "comparison_page").
- Assign a priority ("high" | "medium" | "low") based primarily on the query's \
opportunity score.

Output ONLY a single JSON object matching exactly this schema. No prose, no \
markdown code fences, no keys other than the ones shown:
{
  "recommendations": [
    {
      "target_query_ref": "Q1",
      "content_type": "blog_post" | "landing_page" | "faq" | "comparison_page" | "guide",
      "title": "<specific, publishable content title>",
      "rationale": "<why this closes the gap for this specific query>",
      "target_keywords": ["<keyword or topic>", ...],
      "priority": "high" | "medium" | "low"
    }
  ]
}
"""

USER_PROMPT_TEMPLATE = """Target business: {name}
Domain: {domain}
Industry: {industry}
Description: {description}

Gap queries (target domain not currently appearing):
{query_lines}

Generate 3-5 content recommendations now, following the schema and rules exactly.
"""


@dataclass
class RecommendationAgentItem:
    query_uuid: str
    content_type: str
    title: str
    rationale: str
    target_keywords: list[str]
    priority: str


@dataclass
class RecommendationAgentResult:
    items: list[RecommendationAgentItem]
    tokens_used: int
    degraded: bool = False


class ContentRecommendationAgent(BaseAgent):
    def run(
        self, gap_queries: list[DiscoveredQuery], profile: BusinessProfile
    ) -> RecommendationAgentResult:
        if not gap_queries:
            return RecommendationAgentResult(items=[], tokens_used=0)

        ref_map = {f"Q{i + 1}": query for i, query in enumerate(gap_queries)}
        query_lines = "\n".join(
            f'{ref}: "{query.query_text}" (intent: {query.query_intent or "unknown"}, '
            f"est. monthly volume: {query.estimated_search_volume}, "
            f"difficulty: {query.competitive_difficulty}, "
            f"opportunity score: {query.opportunity_score})"
            for ref, query in ref_map.items()
        )
        user_prompt = USER_PROMPT_TEMPLATE.format(
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            description=profile.description or "(no description provided)",
            query_lines=query_lines,
        )

        try:
            result = self.llm_client.complete_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=self.model,
                schema=RecommendationOutput,
            )
        except Exception:
            logger.exception(
                "ContentRecommendationAgent LLM call failed for profile %s; using "
                "fallback recommendations so the pipeline can continue.",
                profile.uuid,
            )
            return RecommendationAgentResult(
                items=self._fallback_items(ref_map, profile), tokens_used=0, degraded=True
            )

        items: list[RecommendationAgentItem] = []
        for rec in result.data.recommendations:
            query = ref_map.get(rec.target_query_ref)
            if query is None:
                logger.warning(
                    "ContentRecommendationAgent referenced unknown query ref %r; "
                    "dropping that recommendation.",
                    rec.target_query_ref,
                )
                continue
            items.append(
                RecommendationAgentItem(
                    query_uuid=query.uuid,
                    content_type=rec.content_type,
                    title=rec.title,
                    rationale=rec.rationale,
                    target_keywords=rec.target_keywords,
                    priority=rec.priority,
                )
            )

        if not items:
            # Every reference the model returned was invalid -- degrade rather
            # than silently return zero recommendations for a real gap.
            return RecommendationAgentResult(
                items=self._fallback_items(ref_map, profile),
                tokens_used=result.tokens_used,
                degraded=True,
            )

        return RecommendationAgentResult(items=items, tokens_used=result.tokens_used)

    @staticmethod
    def _fallback_items(
        ref_map: dict[str, DiscoveredQuery], profile: BusinessProfile
    ) -> list[RecommendationAgentItem]:
        items = []
        for query in list(ref_map.values())[:3]:
            score = query.opportunity_score or 0.0
            items.append(
                RecommendationAgentItem(
                    query_uuid=query.uuid,
                    content_type="blog_post",
                    title=f'{profile.name}: answering "{query.query_text}"',
                    rationale=(
                        f"{profile.name} does not currently appear in AI-generated "
                        f"answers for this query (opportunity score {score}). Publishing "
                        "dedicated content directly addressing it closes that gap."
                    ),
                    target_keywords=[profile.industry.lower(), profile.name.lower()],
                    priority="high" if score >= 0.7 else "medium",
                )
            )
        return items
