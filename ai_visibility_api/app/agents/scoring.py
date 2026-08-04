"""Agent 2 -- Visibility Scoring.

Combines two independent signals per query:
1. Real-world query metrics (search volume, competitive difficulty) from a
   `DataProvider` -- DataForSEO if configured, a deterministic heuristic
   otherwise. See app/services/data_provider.py.
2. An LLM simulation of how a general-purpose AI assistant would actually
   answer the question, used to determine whether the target domain would
   be mentioned and at what rank.

The two are combined by `compute_opportunity_score` into the final 0-1 score.

Unlike Agent 1/3 (which apply a whole-pipeline fallback if the LLM call
fails), this agent deliberately lets exceptions propagate. Failure isolation
for "one bad query shouldn't kill the run" is a pipeline-level concern --
the orchestrator wraps each per-query call and records `scoring_error`
instead of crashing, per the spec's explicit requirement that Agent 2
failures on one query must not stop the rest from being scored.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import BaseAgent
from app.models.profile import BusinessProfile
from app.schemas.agent_io import VisibilitySimulationOutput
from app.services.data_provider import DataProvider
from app.services.opportunity_score import compute_opportunity_score

SYSTEM_PROMPT = """You are the Visibility Scoring Agent inside an AI-visibility \
analytics platform.

Your job: simulate, as realistically as possible, how a general-purpose AI \
assistant (like ChatGPT or Claude) would answer a specific user question about a \
competitive product space -- then analyze whether one particular target domain \
would be mentioned in that answer, and at what rank.

Process:
1. Mentally generate the answer a well-informed AI assistant would give to the \
user's question today, listing the specific companies/products/domains it would \
recommend, most prominent/most-likely-to-be-mentioned first. Ground this in \
genuine, realistic knowledge of the named competitive space -- do not simply \
invent implausible names, and do not default to always including the target \
domain out of politeness. Some real answers legitimately would not mention it.
2. Extract that ordered list of mentioned entities.
3. Determine whether the target domain given to you appears in that list (by \
name or domain, allowing for reasonable brand-name variants) and its 1-based \
rank if so.
4. Write a 1-2 sentence snippet summarizing what the simulated answer said.

Output ONLY a single JSON object matching exactly this schema. No prose, no \
markdown code fences, no keys other than the ones shown:
{
  "domain_mentioned": true | false,
  "mention_position": <integer rank 1-20, or null if not mentioned>,
  "mentioned_entities": ["<entity 1>", "<entity 2>", ...],
  "answer_snippet": "<1-2 sentence summary of the simulated answer>"
}
"""

USER_PROMPT_TEMPLATE = """Target business: {name}
Target domain: {domain}
Industry: {industry}
Known competitors: {competitors}

User question asked to the AI assistant: "{query_text}"
Question intent category: {query_intent}

Simulate the assistant's answer and analyze whether {domain} would be mentioned.
"""


@dataclass
class ScoringAgentResult:
    estimated_search_volume: int
    competitive_difficulty: int
    data_source: str
    domain_visible: bool
    visibility_position: int | None
    ai_answer_snippet: str
    opportunity_score: float
    tokens_used: int


class VisibilityScoringAgent(BaseAgent):
    def __init__(self, llm_client, model: str, data_provider: DataProvider):
        super().__init__(llm_client, model)
        self.data_provider = data_provider

    def run(
        self, *, query_text: str, query_intent: str | None, profile: BusinessProfile
    ) -> ScoringAgentResult:
        metrics = self.data_provider.get_query_metrics(query_text)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            competitors=", ".join(profile.competitors) if profile.competitors else "(none)",
            query_text=query_text,
            query_intent=query_intent or "informational",
        )
        result = self.llm_client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=self.model,
            schema=VisibilitySimulationOutput,
        )
        simulation: VisibilitySimulationOutput = result.data

        opportunity_score = compute_opportunity_score(
            estimated_search_volume=metrics.estimated_search_volume,
            competitive_difficulty=metrics.competitive_difficulty,
            domain_visible=simulation.domain_mentioned,
            visibility_position=simulation.mention_position,
            query_intent=query_intent,
        )

        return ScoringAgentResult(
            estimated_search_volume=metrics.estimated_search_volume,
            competitive_difficulty=metrics.competitive_difficulty,
            data_source=metrics.source,
            domain_visible=simulation.domain_mentioned,
            visibility_position=simulation.mention_position,
            ai_answer_snippet=simulation.answer_snippet,
            opportunity_score=opportunity_score,
            tokens_used=result.tokens_used,
        )
