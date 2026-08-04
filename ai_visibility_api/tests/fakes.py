"""Test doubles that stand in for the real OpenAI-backed LLMClient and the
real/heuristic DataProvider, so agent and API tests run fully offline and
deterministically -- no network calls, no API key required.
"""
from __future__ import annotations

from app.services.data_provider import DataProvider, QueryMetrics
from app.services.llm_client import LLMOutputError, LLMResult


class FakeLLMClient:
    """Returns pre-programmed responses keyed by output schema class.

    `responses[schema]` may be a single BaseModel instance (returned every
    call) or a list (popped in order, one per call -- useful when a test
    exercises the same schema multiple times, e.g. one VisibilityScoringAgent
    call per query, with a different simulated answer each time).
    """

    def __init__(self, responses=None, raise_for=None):
        self.responses = dict(responses or {})
        self.raise_for = set(raise_for or set())
        self.calls: list[dict] = []

    def complete_json(
        self, *, system_prompt, user_prompt, model, schema, max_retries=1, temperature=0.4
    ):
        self.calls.append({"schema": schema, "model": model, "user_prompt": user_prompt})

        if schema in self.raise_for:
            raise LLMOutputError("simulated LLM failure for test")

        entry = self.responses[schema]
        if isinstance(entry, list):
            data = entry.pop(0) if len(entry) > 1 else entry[0]
        else:
            data = entry

        return LLMResult(data=data, tokens_used=42, raw_text="{}", model=model)


class FakeDataProvider(DataProvider):
    """Deterministic, test-controlled stand-in for real/heuristic query metrics."""

    def __init__(self, volume: int = 1000, difficulty: int = 50):
        self.volume = volume
        self.difficulty = difficulty
        self.calls: list[str] = []

    def get_query_metrics(self, query_text: str) -> QueryMetrics:
        self.calls.append(query_text)
        return QueryMetrics(
            estimated_search_volume=self.volume,
            competitive_difficulty=self.difficulty,
            source="fake",
        )
