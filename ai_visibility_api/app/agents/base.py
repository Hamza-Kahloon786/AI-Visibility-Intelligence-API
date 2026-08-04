from __future__ import annotations

from app.services.llm_client import LLMClient


class BaseAgent:
    """Shared plumbing for the three pipeline agents.

    Each agent only needs an LLM client and the model it should call --
    everything else (prompts, output schema, fallback behaviour) is specific
    to that agent and lives in its own module, not here.
    """

    def __init__(self, llm_client: LLMClient, model: str):
        self.llm_client = llm_client
        self.model = model
