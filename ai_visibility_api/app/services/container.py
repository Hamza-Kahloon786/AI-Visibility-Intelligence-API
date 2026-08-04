"""Wires the concrete LLM client, data provider, and agents into a
PipelineOrchestrator from app config. Kept separate from create_app() so the
wiring can be swapped out easily in tests (e.g. injecting a fake LLMClient).
"""
from __future__ import annotations

from app.agents.discovery import QueryDiscoveryAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.agents.scoring import VisibilityScoringAgent
from app.services.data_provider import get_data_provider
from app.services.llm_client import LLMClient
from app.services.pipeline import PipelineOrchestrator


def build_pipeline_orchestrator(config) -> PipelineOrchestrator:
    """`config` is a Flask `app.config` object (dict-like), not the plain
    `app.config.Config` class -- use item access, not attribute access."""
    llm_client = LLMClient(api_key=config["OPENAI_API_KEY"])
    data_provider = get_data_provider(config)

    discovery_agent = QueryDiscoveryAgent(llm_client, model=config["OPENAI_MODEL_DISCOVERY"])
    scoring_agent = VisibilityScoringAgent(
        llm_client, model=config["OPENAI_MODEL_SCORING"], data_provider=data_provider
    )
    recommendation_agent = ContentRecommendationAgent(
        llm_client, model=config["OPENAI_MODEL_RECOMMENDATION"]
    )

    return PipelineOrchestrator(
        discovery_agent=discovery_agent,
        scoring_agent=scoring_agent,
        recommendation_agent=recommendation_agent,
        max_discovery_queries=config["MAX_DISCOVERY_QUERIES"],
        max_gap_queries=config["MAX_GAP_QUERIES_FOR_RECOMMENDATIONS"],
    )
