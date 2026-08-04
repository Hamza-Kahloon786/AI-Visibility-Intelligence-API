"""Thin wrapper around the OpenAI Chat Completions API.

Centralises the two things every agent needs and none of them should
reimplement: (1) forcing/validating structured JSON output, and (2) retrying
once with a corrective prompt when the model doesn't comply, before giving up
with a typed error the caller can act on. This is what lets each agent's
prompt module stay focused purely on *what* to ask, not on JSON plumbing.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Type, TypeVar

from openai import APIError, OpenAI
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMOutputError(Exception):
    """Raised when the LLM fails to produce schema-valid JSON after retries."""


@dataclass
class LLMResult:
    data: BaseModel
    tokens_used: int
    raw_text: str
    model: str


class LLMClient:
    """Wraps a single OpenAI client. One instance is shared across agents."""

    def __init__(self, api_key: str | None):
        # Deferred failure: instantiate lazily so a missing key only breaks
        # the request path that actually needs the LLM, not app startup/tests.
        self._api_key = api_key
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not self._api_key:
                raise LLMOutputError(
                    "OPENAI_API_KEY is not configured; cannot call the LLM."
                )
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        schema: Type[SchemaT],
        max_retries: int = 1,
        temperature: float = 0.4,
    ) -> LLMResult:
        """Call the model and parse+validate its output against `schema`.

        On invalid JSON or a schema mismatch, retries up to `max_retries`
        times with a corrective follow-up message that includes the bad
        output and the validation error, before raising LLMOutputError.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        tokens_used = 0
        last_error: Exception | None = None
        last_raw = ""

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
            except APIError as exc:
                raise LLMOutputError(f"OpenAI API error: {exc}") from exc

            usage = getattr(response, "usage", None)
            tokens_used += usage.total_tokens if usage else 0
            raw_text = response.choices[0].message.content or ""
            last_raw = raw_text

            try:
                parsed = json.loads(raw_text)
                validated = schema.model_validate(parsed)
                return LLMResult(
                    data=validated, tokens_used=tokens_used, raw_text=raw_text, model=model
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "LLM output failed validation (attempt %s/%s): %s",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                messages.append({"role": "assistant", "content": raw_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was not valid JSON matching the "
                            f"required schema. Validation error: {exc}\n"
                            "Return ONLY a corrected JSON object. No prose, no markdown "
                            "fences, no explanation -- the entire response must be "
                            "parseable by json.loads()."
                        ),
                    }
                )

        raise LLMOutputError(
            f"LLM failed to produce schema-valid JSON after {max_retries + 1} attempts: "
            f"{last_error}. Last raw output: {last_raw[:500]!r}"
        )
