"""Pydantic schemas the LLM's JSON output is validated against.

These are passed straight into `LLMClient.complete_json(schema=...)`. If the
model's JSON doesn't satisfy these constraints (wrong types, missing keys,
intent outside the enum, wrong list length) pydantic raises `ValidationError`,
which `LLMClient` treats the same as malformed JSON: retry once with a
corrective prompt, then surface `LLMOutputError` to the agent so it can fall
back rather than crash the pipeline.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

QueryIntent = Literal["comparison", "transactional", "informational", "navigational"]
ContentType = Literal["blog_post", "landing_page", "faq", "comparison_page", "guide"]
Priority = Literal["high", "medium", "low"]


# --- Agent 1: Query Discovery -------------------------------------------------


class DiscoveredQueryItem(BaseModel):
    query_text: str = Field(min_length=8, max_length=300)
    query_intent: QueryIntent


class DiscoveryOutput(BaseModel):
    queries: list[DiscoveredQueryItem] = Field(min_length=5, max_length=25)


# --- Agent 2: Visibility Scoring ----------------------------------------------


class VisibilitySimulationOutput(BaseModel):
    """One simulated "how would an AI assistant answer this?" check."""

    domain_mentioned: bool
    mention_position: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description="1-based rank of the target domain among entities mentioned in the "
        "simulated answer; null if not mentioned.",
    )
    mentioned_entities: list[str] = Field(default_factory=list, max_length=10)
    answer_snippet: str = Field(max_length=600)


# --- Agent 3: Content Recommendation ------------------------------------------


class RecommendationItem(BaseModel):
    target_query_ref: str = Field(
        description="The Qn reference key from the prompt's gap-query list, e.g. 'Q1'."
    )
    content_type: ContentType
    title: str = Field(min_length=5, max_length=200)
    rationale: str = Field(min_length=10, max_length=800)
    target_keywords: list[str] = Field(min_length=1, max_length=10)
    priority: Priority


class RecommendationOutput(BaseModel):
    recommendations: list[RecommendationItem] = Field(min_length=1, max_length=5)
