from app.agents.discovery import QueryDiscoveryAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.agents.scoring import VisibilityScoringAgent
from app.models.profile import BusinessProfile
from app.models.query import DiscoveredQuery
from app.schemas.agent_io import (
    DiscoveredQueryItem,
    DiscoveryOutput,
    RecommendationItem,
    RecommendationOutput,
    VisibilitySimulationOutput,
)
from app.services.opportunity_score import compute_opportunity_score
from tests.fakes import FakeDataProvider, FakeLLMClient


def _profile(**overrides) -> BusinessProfile:
    defaults = dict(
        name="Frase",
        domain="frase.io",
        industry="SEO Content Tools",
        description="AI-powered content briefs",
        competitors=["surferseo.com", "marketmuse.com"],
    )
    defaults.update(overrides)
    return BusinessProfile(**defaults)


# --- Agent 1: QueryDiscoveryAgent ---------------------------------------------


def test_discovery_agent_returns_validated_queries_on_success():
    output = DiscoveryOutput(
        queries=[
            DiscoveredQueryItem(query_text="What is the best AI SEO tool?", query_intent="transactional"),
            DiscoveredQueryItem(query_text="Frase vs Surfer SEO?", query_intent="comparison"),
            DiscoveredQueryItem(query_text="Is Frase good for beginners?", query_intent="navigational"),
            DiscoveredQueryItem(query_text="How do I write SEO content briefs with AI?", query_intent="informational"),
            DiscoveredQueryItem(query_text="What are the best MarketMuse alternatives?", query_intent="transactional"),
        ]
    )
    fake_llm = FakeLLMClient(responses={DiscoveryOutput: output})
    agent = QueryDiscoveryAgent(fake_llm, model="gpt-4o")

    result = agent.run(_profile())

    assert result.degraded is False
    assert len(result.queries) == 5
    assert result.tokens_used == 42
    assert fake_llm.calls[0]["schema"] is DiscoveryOutput


def test_discovery_agent_falls_back_when_llm_fails_after_retries():
    fake_llm = FakeLLMClient(raise_for={DiscoveryOutput})
    agent = QueryDiscoveryAgent(fake_llm, model="gpt-4o")

    result = agent.run(_profile())

    assert result.degraded is True
    assert result.tokens_used == 0
    assert len(result.queries) >= 5  # pipeline must still have something to score
    assert all(isinstance(q, DiscoveredQueryItem) for q in result.queries)


# --- Agent 2: VisibilityScoringAgent -------------------------------------------


def test_scoring_agent_combines_real_metrics_with_llm_visibility_simulation():
    simulation = VisibilitySimulationOutput(
        domain_mentioned=False,
        mention_position=None,
        mentioned_entities=["Surfer SEO", "MarketMuse"],
        answer_snippet="The assistant recommends Surfer SEO and MarketMuse.",
    )
    fake_llm = FakeLLMClient(responses={VisibilitySimulationOutput: simulation})
    fake_data = FakeDataProvider(volume=1200, difficulty=62)
    agent = VisibilityScoringAgent(fake_llm, model="gpt-4o-mini", data_provider=fake_data)

    result = agent.run(query_text="What is the best AI SEO tool?", query_intent="transactional", profile=_profile())

    assert result.estimated_search_volume == 1200
    assert result.competitive_difficulty == 62
    assert result.data_source == "fake"
    assert result.domain_visible is False
    assert result.visibility_position is None
    expected_score = compute_opportunity_score(
        estimated_search_volume=1200,
        competitive_difficulty=62,
        domain_visible=False,
        visibility_position=None,
        query_intent="transactional",
    )
    assert result.opportunity_score == expected_score
    assert fake_data.calls == ["What is the best AI SEO tool?"]


def test_scoring_agent_propagates_llm_failure_for_orchestrator_to_isolate():
    # Deliberate: per-query failure isolation is the orchestrator's job (see
    # services/pipeline.py), not this agent's -- so it must raise, not swallow.
    fake_llm = FakeLLMClient(raise_for={VisibilitySimulationOutput})
    fake_data = FakeDataProvider()
    agent = VisibilityScoringAgent(fake_llm, model="gpt-4o-mini", data_provider=fake_data)

    try:
        agent.run(query_text="anything", query_intent="informational", profile=_profile())
        assert False, "expected an exception to propagate"
    except Exception:
        pass


# --- Agent 3: ContentRecommendationAgent ---------------------------------------


def _gap_query(uuid: str, text: str, score: float) -> DiscoveredQuery:
    return DiscoveredQuery(
        uuid=uuid,
        query_text=text,
        query_intent="comparison",
        estimated_search_volume=1200,
        competitive_difficulty=60,
        opportunity_score=score,
        domain_visible=False,
    )


def test_recommendation_agent_maps_query_refs_back_to_uuids():
    gap_queries = [
        _gap_query("q-1", "What is the best AI SEO tool?", 0.81),
        _gap_query("q-2", "Frase vs Surfer SEO?", 0.75),
    ]
    output = RecommendationOutput(
        recommendations=[
            RecommendationItem(
                target_query_ref="Q2",
                content_type="comparison_page",
                title="Frase vs Surfer SEO: Which Is Better for Content Teams?",
                rationale="Closes the direct comparison gap for this query.",
                target_keywords=["frase vs surfer seo", "content brief tool"],
                priority="high",
            )
        ]
    )
    fake_llm = FakeLLMClient(responses={RecommendationOutput: output})
    agent = ContentRecommendationAgent(fake_llm, model="gpt-4o")

    result = agent.run(gap_queries, _profile())

    assert result.degraded is False
    assert len(result.items) == 1
    assert result.items[0].query_uuid == "q-2"  # resolved from "Q2", not "Q1"


def test_recommendation_agent_drops_invalid_refs_and_falls_back_if_all_invalid():
    gap_queries = [_gap_query("q-1", "What is the best AI SEO tool?", 0.81)]
    output = RecommendationOutput(
        recommendations=[
            RecommendationItem(
                target_query_ref="Q99",  # hallucinated ref not in the prompt's map
                content_type="blog_post",
                title="Some Title",
                rationale="Some rationale that is long enough.",
                target_keywords=["kw"],
                priority="medium",
            )
        ]
    )
    fake_llm = FakeLLMClient(responses={RecommendationOutput: output})
    agent = ContentRecommendationAgent(fake_llm, model="gpt-4o")

    result = agent.run(gap_queries, _profile())

    assert result.degraded is True
    assert len(result.items) == 1
    assert result.items[0].query_uuid == "q-1"  # fallback still targets a real query


def test_recommendation_agent_skips_llm_entirely_when_no_gap_queries():
    fake_llm = FakeLLMClient(responses={})
    agent = ContentRecommendationAgent(fake_llm, model="gpt-4o")

    result = agent.run([], _profile())

    assert result.items == []
    assert result.tokens_used == 0
    assert fake_llm.calls == []
