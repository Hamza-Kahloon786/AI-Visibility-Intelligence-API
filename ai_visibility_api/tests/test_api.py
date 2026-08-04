from app.agents.discovery import QueryDiscoveryAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.agents.scoring import VisibilityScoringAgent
from app.schemas.agent_io import (
    DiscoveredQueryItem,
    DiscoveryOutput,
    RecommendationItem,
    RecommendationOutput,
    VisibilitySimulationOutput,
)
from app.services.pipeline import PipelineOrchestrator
from tests.fakes import FakeDataProvider, FakeLLMClient


def _build_fake_orchestrator() -> PipelineOrchestrator:
    """A fully offline PipelineOrchestrator: 5 discovered queries, 3 of which
    come back "not visible" (gap queries) and 2 "visible". Two content
    recommendations get generated against whichever 2 gap queries end up
    first once the orchestrator sorts them by opportunity score -- tests
    assert on counts/membership rather than a specific query, since that
    sort order depends on the opportunity score formula, not fixture order.
    Lets API tests exercise the whole discover -> score -> recommend flow
    with no network calls."""
    discovery_output = DiscoveryOutput(
        queries=[
            DiscoveredQueryItem(query_text="What is the best AI SEO tool?", query_intent="transactional"),
            DiscoveredQueryItem(query_text="Frase vs Surfer SEO?", query_intent="comparison"),
            DiscoveredQueryItem(query_text="Is Frase good for beginners?", query_intent="navigational"),
            DiscoveredQueryItem(query_text="How do I write SEO content briefs with AI?", query_intent="informational"),
            DiscoveredQueryItem(query_text="What are the best MarketMuse alternatives?", query_intent="transactional"),
        ]
    )
    visibility_outputs = [
        VisibilitySimulationOutput(
            domain_mentioned=False, mention_position=None,
            mentioned_entities=["Surfer SEO"], answer_snippet="Recommends Surfer SEO.",
        ),
        VisibilitySimulationOutput(
            domain_mentioned=False, mention_position=None,
            mentioned_entities=["MarketMuse"], answer_snippet="Recommends MarketMuse.",
        ),
        VisibilitySimulationOutput(
            domain_mentioned=True, mention_position=1,
            mentioned_entities=["Frase"], answer_snippet="Recommends Frase first.",
        ),
        VisibilitySimulationOutput(
            domain_mentioned=False, mention_position=None,
            mentioned_entities=["Clearscope"], answer_snippet="Recommends Clearscope.",
        ),
        VisibilitySimulationOutput(
            domain_mentioned=True, mention_position=3,
            mentioned_entities=["MarketMuse", "Surfer SEO", "Frase"], answer_snippet="Mentions Frase third.",
        ),
    ]
    recommendation_output = RecommendationOutput(
        recommendations=[
            RecommendationItem(
                target_query_ref="Q1", content_type="blog_post",
                title="Closing the top-ranked visibility gap",
                rationale="Directly answers the highest opportunity-score gap query where Frase is absent.",
                target_keywords=["best ai seo tool"], priority="high",
            ),
            RecommendationItem(
                target_query_ref="Q2", content_type="comparison_page",
                title="Closing the second-ranked visibility gap",
                rationale="Directly answers the next highest opportunity-score gap query where Frase is absent.",
                target_keywords=["frase vs surfer seo"], priority="high",
            ),
        ]
    )

    fake_llm = FakeLLMClient(
        responses={
            DiscoveryOutput: discovery_output,
            VisibilitySimulationOutput: visibility_outputs,
            RecommendationOutput: recommendation_output,
        }
    )
    fake_data = FakeDataProvider(volume=1200, difficulty=60)

    return PipelineOrchestrator(
        discovery_agent=QueryDiscoveryAgent(fake_llm, model="gpt-4o"),
        scoring_agent=VisibilityScoringAgent(fake_llm, model="gpt-4o-mini", data_provider=fake_data),
        recommendation_agent=ContentRecommendationAgent(fake_llm, model="gpt-4o"),
        max_discovery_queries=18,
        max_gap_queries=8,
    )


def test_create_profile_returns_201_with_expected_shape(client):
    response = client.post(
        "/api/v1/profiles",
        json={
            "name": "Frase",
            "domain": "https://www.frase.io/",
            "industry": "SEO Content Tools",
            "description": "AI-powered content briefs",
            "competitors": ["SurferSEO.com", "marketmuse.com"],
        },
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["name"] == "Frase"
    assert body["domain"] == "frase.io"  # protocol/www stripped by schema
    assert body["competitors"] == ["surferseo.com", "marketmuse.com"]
    assert body["status"] == "created"
    assert "profile_uuid" in body and "created_at" in body


def test_create_profile_validation_error_returns_400_with_consistent_error_shape(client):
    response = client.post("/api/v1/profiles", json={"domain": "frase.io"})  # missing required fields
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["error"]["details"], list)


def test_get_profile_not_found_returns_404_with_consistent_error_shape(client):
    response = client.get("/api/v1/profiles/does-not-exist")
    assert response.status_code == 404
    body = response.get_json()
    assert body["error"]["code"] == "profile_not_found"


def test_full_pipeline_run_discovers_scores_and_recommends(app, client, sample_profile):
    app.pipeline_orchestrator = _build_fake_orchestrator()

    response = client.post(f"/api/v1/profiles/{sample_profile.uuid}/run")
    assert response.status_code == 201
    body = response.get_json()

    assert body["status"] == "completed"
    assert body["queries_discovered"] == 5
    assert body["queries_scored"] == 5
    assert body["tokens_used"] > 0
    assert len(body["top_opportunity_queries"]) == 3
    assert len(body["content_recommendations"]) == 2

    not_visible_uuids = {
        q["query_uuid"]
        for q in client.get(
            f"/api/v1/profiles/{sample_profile.uuid}/queries?status=not_visible"
        ).get_json()["queries"]
    }
    assert len(not_visible_uuids) == 3
    assert all(
        rec["target_query_uuid"] in not_visible_uuids
        for rec in body["content_recommendations"]
    )


def test_list_queries_supports_status_and_min_score_filters(app, client, sample_profile):
    app.pipeline_orchestrator = _build_fake_orchestrator()
    client.post(f"/api/v1/profiles/{sample_profile.uuid}/run")

    not_visible = client.get(
        f"/api/v1/profiles/{sample_profile.uuid}/queries?status=not_visible"
    ).get_json()
    assert not_visible["total"] == 3
    assert all(q["domain_visible"] is False for q in not_visible["queries"])

    visible = client.get(
        f"/api/v1/profiles/{sample_profile.uuid}/queries?status=visible"
    ).get_json()
    assert visible["total"] == 2

    high_score = client.get(
        f"/api/v1/profiles/{sample_profile.uuid}/queries?min_score=0.99"
    ).get_json()
    assert high_score["total"] == 0  # nothing scores that high with these fixtures


def test_list_queries_rejects_invalid_status_param(app, client, sample_profile):
    response = client.get(f"/api/v1/profiles/{sample_profile.uuid}/queries?status=bogus")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_query_param"


def test_recommendations_endpoint_returns_generated_recommendations(app, client, sample_profile):
    app.pipeline_orchestrator = _build_fake_orchestrator()
    client.post(f"/api/v1/profiles/{sample_profile.uuid}/run")

    response = client.get(f"/api/v1/profiles/{sample_profile.uuid}/recommendations")
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["recommendations"]) == 2
    assert {"recommendation_uuid", "target_query_uuid", "priority"} <= body["recommendations"][0].keys()


def test_recheck_updates_a_single_query(app, client, sample_profile):
    app.pipeline_orchestrator = _build_fake_orchestrator()
    run_body = client.post(f"/api/v1/profiles/{sample_profile.uuid}/run").get_json()
    query_uuid = run_body["top_opportunity_queries"][0]["query_uuid"]

    # Re-point the scoring agent at a fresh fake so we can assert the
    # recheck actually re-ran scoring rather than just echoing stale data.
    fresh_llm = FakeLLMClient(
        responses={
            VisibilitySimulationOutput: VisibilitySimulationOutput(
                domain_mentioned=True, mention_position=2,
                mentioned_entities=["Frase", "Surfer SEO"], answer_snippet="Now mentions Frase.",
            )
        }
    )
    app.pipeline_orchestrator.scoring_agent = VisibilityScoringAgent(
        fresh_llm, model="gpt-4o-mini", data_provider=FakeDataProvider(volume=500, difficulty=40)
    )

    response = client.post(f"/api/v1/queries/{query_uuid}/recheck")
    assert response.status_code == 200
    body = response.get_json()
    assert body["domain_visible"] is True
    assert body["visibility_position"] == 2
    assert body["estimated_search_volume"] == 500
    assert body["last_checked_at"] is not None


def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
