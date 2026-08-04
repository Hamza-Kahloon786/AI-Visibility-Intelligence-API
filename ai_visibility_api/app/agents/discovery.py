"""Agent 1 -- Query Discovery.

Given a business profile, generates the natural-language questions real
people ask AI assistants when researching this competitive space.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agents.base import BaseAgent
from app.models.profile import BusinessProfile
from app.schemas.agent_io import DiscoveredQueryItem, DiscoveryOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Query Discovery Agent inside an AI-visibility analytics platform.

Your job: given a business's profile, generate the realistic, natural-language \
questions real people type into AI assistants (ChatGPT, Claude, Perplexity) while \
researching products or services in that business's competitive space. These are \
end-user questions, not SEO keyword fragments and not questions about the \
business's internal operations.

Requirements for every generated query:
- Natural language, phrased the way a person actually types into a chat assistant \
(a full question or comparison request, not a keyword fragment).
- Commercially relevant: whoever asks this is evaluating, comparing, or about to \
choose a product/vendor in this space -- not idle curiosity.
- Cover a diverse mix of these four intents, and label each query with exactly \
one of them:
  - "comparison": e.g. "How does X compare to Y?", "X vs Y for small teams"
  - "transactional": e.g. "What is the best X for Y?", "Top X tools in 2025"
  - "informational": e.g. "How do I do X?", "What is X and how does it work?" \
(still relevant to a buying decision in this space, not generic trivia)
  - "navigational": e.g. "Is X any good?", "X reviews", "X pricing"
- Use the specific competitor names/domains given to you (not invented ones) in \
roughly a third of the comparison/transactional queries.
- Do not put the target business's own name in every query -- most real searches \
in this space are category- or competitor-first, not brand-first.
- Generate between 10 and 20 queries total.

Output ONLY a single JSON object matching exactly this schema. No prose, no \
markdown code fences, no keys other than the ones shown:
{
  "queries": [
    {
      "query_text": "<natural language question a real user would ask>",
      "query_intent": "comparison" | "transactional" | "informational" | "navigational"
    }
  ]
}
"""

USER_PROMPT_TEMPLATE = """Business profile:
- Name: {name}
- Domain: {domain}
- Industry: {industry}
- Description: {description}
- Known competitors: {competitors}

Generate the discovery query set now, following the schema and rules exactly.
"""


@dataclass
class DiscoveryAgentResult:
    queries: list[DiscoveredQueryItem]
    tokens_used: int
    degraded: bool = False


class QueryDiscoveryAgent(BaseAgent):
    def run(self, profile: BusinessProfile) -> DiscoveryAgentResult:
        competitors = ", ".join(profile.competitors) if profile.competitors else "(none provided)"
        user_prompt = USER_PROMPT_TEMPLATE.format(
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            description=profile.description or "(no description provided)",
            competitors=competitors,
        )

        try:
            result = self.llm_client.complete_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=self.model,
                schema=DiscoveryOutput,
            )
            return DiscoveryAgentResult(
                queries=result.data.queries, tokens_used=result.tokens_used
            )
        except Exception:
            logger.exception(
                "QueryDiscoveryAgent LLM call failed for profile %s; using fallback "
                "query set so the pipeline can continue.",
                profile.uuid,
            )
            return DiscoveryAgentResult(
                queries=self._fallback_queries(profile), tokens_used=0, degraded=True
            )

    @staticmethod
    def _fallback_queries(profile: BusinessProfile) -> list[DiscoveredQueryItem]:
        competitors = profile.competitors or ["a leading competitor"]
        templates = [
            (f"What is the best {profile.industry} tool available today?", "transactional"),
            (f"What is the best {profile.industry} tool for small teams?", "transactional"),
            (f"Is {profile.name} worth using for {profile.industry.lower()}?", "navigational"),
            (f"{profile.name} vs {competitors[0]} -- which is better?", "comparison"),
            (f"How do I choose a {profile.industry} provider?", "informational"),
            (f"What are the top alternatives to {competitors[0]}?", "transactional"),
            (f"How does {profile.name} compare to {competitors[0]}?", "comparison"),
            (f"What should I look for in a {profile.industry} solution?", "informational"),
            (f"Is {competitors[0]} or {profile.name} better for beginners?", "comparison"),
            (f"What are the pricing options for {profile.industry} tools?", "navigational"),
        ]
        return [
            DiscoveredQueryItem(query_text=text, query_intent=intent)
            for text, intent in templates
        ]
