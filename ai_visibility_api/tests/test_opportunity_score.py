from app.services.opportunity_score import compute_opportunity_score


def _score(**overrides):
    defaults = dict(
        estimated_search_volume=1000,
        competitive_difficulty=50,
        domain_visible=False,
        visibility_position=None,
        query_intent="informational",
    )
    defaults.update(overrides)
    return compute_opportunity_score(**defaults)


def test_score_is_always_within_bounds():
    assert 0.0 <= _score(estimated_search_volume=0, competitive_difficulty=100) <= 1.0
    assert 0.0 <= _score(estimated_search_volume=1_000_000, competitive_difficulty=0) <= 1.0


def test_not_visible_scores_higher_than_visible_top_position():
    not_visible = _score(domain_visible=False)
    visible_top = _score(domain_visible=True, visibility_position=1)
    assert not_visible > visible_top


def test_visible_position_further_down_scores_higher_than_top_position():
    top = _score(domain_visible=True, visibility_position=1)
    buried = _score(domain_visible=True, visibility_position=10)
    assert buried > top


def test_higher_volume_scores_higher_all_else_equal():
    low_volume = _score(estimated_search_volume=10)
    high_volume = _score(estimated_search_volume=10_000)
    assert high_volume > low_volume


def test_lower_difficulty_scores_higher_all_else_equal():
    easy = _score(competitive_difficulty=10)
    hard = _score(competitive_difficulty=90)
    assert easy > hard


def test_comparison_intent_scores_higher_than_navigational_all_else_equal():
    comparison = _score(query_intent="comparison")
    navigational = _score(query_intent="navigational")
    assert comparison > navigational


def test_unknown_intent_falls_back_to_default_weight_without_crashing():
    # Should not raise even if the LLM/agent gives an intent string outside
    # the known enum -- opportunity scoring must never crash the pipeline.
    score = _score(query_intent="something_unexpected")
    assert 0.0 <= score <= 1.0


def test_unscored_visibility_none_is_treated_as_a_mild_neutral_gap():
    unscored = _score(domain_visible=None)
    not_visible = _score(domain_visible=False)
    visible_top = _score(domain_visible=True, visibility_position=1)
    assert visible_top < unscored < not_visible
