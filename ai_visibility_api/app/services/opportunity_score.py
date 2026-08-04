"""Opportunity score formula.

score = 0.30 * volume_norm
      + 0.20 * ease_of_ranking       (= 1 - difficulty/100)
      + 0.35 * visibility_gap
      + 0.15 * intent_weight

Rationale for the weights (documented in more detail in the README):

- `visibility_gap` gets the largest weight (0.35). The whole point of this
  product is finding where the target domain is *absent* from AI answers --
  a query the domain already dominates is not an "opportunity" no matter how
  big or easy it is, so absence/weak presence has to dominate the score.
- `volume_norm` (0.30) is log-scaled, not linear. Raw monthly search volume
  for these queries can range from ~10 to 50,000+; a linear blend would let
  one viral head-term completely drown out the difficulty/gap/intent
  signals. log10 compresses that range so a 10x volume difference matters,
  but not 10x as much as e.g. going from invisible to visible.
- `ease_of_ranking` (0.20) rewards queries that are realistically winnable
  soon, not just theoretically valuable.
- `intent_weight` (0.15) is the smallest factor deliberately: intent is a
  useful tie-breaker (a comparison query converts better than a purely
  informational one) but shouldn't outweigh actual volume/gap/difficulty
  signal, since intent classification is the least reliable of the four
  inputs (LLM-assigned, not measured).

All sub-scores are normalised to [0, 1] before weighting, and the final
result is clamped to [0, 1] as a defensive measure against float drift.
"""
from __future__ import annotations

import math

VOLUME_WEIGHT = 0.30
EASE_WEIGHT = 0.20
VISIBILITY_GAP_WEIGHT = 0.35
INTENT_WEIGHT = 0.15

# Monthly search volume at/above this is treated as "as good as it gets" for
# normalisation purposes -- log-scaled so outliers don't dominate the score.
REFERENCE_MAX_VOLUME = 10_000

INTENT_WEIGHTS = {
    "comparison": 1.0,
    "transactional": 0.9,
    "navigational": 0.5,
    "informational": 0.6,
}
DEFAULT_INTENT_WEIGHT = 0.6


def _volume_norm(estimated_search_volume: int) -> float:
    volume = max(estimated_search_volume, 0)
    normalized = math.log10(volume + 1) / math.log10(REFERENCE_MAX_VOLUME + 1)
    return min(max(normalized, 0.0), 1.0)


def _ease_of_ranking(competitive_difficulty: int) -> float:
    difficulty = min(max(competitive_difficulty, 0), 100)
    return 1.0 - (difficulty / 100.0)


def _visibility_gap(domain_visible: bool | None, visibility_position: int | None) -> float:
    if domain_visible is None:
        # Not yet scored -- treat as a mild, neutral gap rather than 0 or 1
        # so a partially-failed scoring pass doesn't silently zero it out.
        return 0.6
    if domain_visible is False:
        return 1.0
    # Visible: the higher/earlier the mention, the smaller the remaining gap.
    if visibility_position is None:
        return 0.3
    if visibility_position <= 3:
        return 0.05
    if visibility_position <= 6:
        return 0.25
    return 0.5


def _intent_weight(query_intent: str | None) -> float:
    if not query_intent:
        return DEFAULT_INTENT_WEIGHT
    return INTENT_WEIGHTS.get(query_intent.lower(), DEFAULT_INTENT_WEIGHT)


def compute_opportunity_score(
    *,
    estimated_search_volume: int,
    competitive_difficulty: int,
    domain_visible: bool | None,
    visibility_position: int | None = None,
    query_intent: str | None = None,
) -> float:
    volume_component = VOLUME_WEIGHT * _volume_norm(estimated_search_volume)
    ease_component = EASE_WEIGHT * _ease_of_ranking(competitive_difficulty)
    gap_component = VISIBILITY_GAP_WEIGHT * _visibility_gap(domain_visible, visibility_position)
    intent_component = INTENT_WEIGHT * _intent_weight(query_intent)

    score = volume_component + ease_component + gap_component + intent_component
    return round(min(max(score, 0.0), 1.0), 4)
