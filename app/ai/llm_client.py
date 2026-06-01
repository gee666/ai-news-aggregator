"""Configurable LLM router backed by the local pi agent."""

from __future__ import annotations

from typing import Any, Literal, Sequence

from app.ai.pi_client import LLMResponse, PiAgentClient
from app.ai.pi_client import is_configured as pi_is_configured
from app.config import get_settings

Route = Literal["smart", "cheap"]


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        if self.settings.llm_provider != "pi":
            raise ValueError(f"Unsupported LLM_PROVIDER: {self.settings.llm_provider}")
        self._client = PiAgentClient()

    def model_for_route(self, route: Route = "smart") -> str:
        return self._client.model_for_route(route)

    async def complete(
        self,
        prompt: str,
        *,
        route: Route = "smart",
        instructions: str | None = None,
        json_schema: dict[str, Any] | None = None,
        tools: Sequence[str] | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Run a completion through the pi agent.

        ``tools`` is an optional allowlist of pi tool names (e.g.
        ``["web_search", "Bash"]``). When omitted, pi runs with all tools
        disabled.
        """
        return await self._client.create_response(
            prompt,
            route=route,
            instructions=instructions,
            json_schema=json_schema,
            tools=tools,
            temperature=temperature,
        )


def is_configured() -> bool:
    settings = get_settings()
    return settings.llm_provider == "pi" and pi_is_configured()
