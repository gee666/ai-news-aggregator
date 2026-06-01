"""LLM client that delegates every completion to the pi agent.

Instead of talking to a remote OpenAI/Codex endpoint, this client spawns the
local ``pi`` coding agent as a subprocess (``pi -p "<prompt>"``) and reads the
final assistant text from stdout.

Tool control: by default pi is launched with ``--no-tools`` because the
summarization / extraction / dedup prompts only need plain reasoning. Callers
that need live web research can pass ``tools=["web_search", "Bash"]`` so the pi
agent can search the web and fetch links from bash, without exposing the
read/write/edit tools.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from app.config import get_settings

Route = Literal["smart", "cheap"]


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    raw: dict[str, Any]


class PiAgentError(RuntimeError):
    """Raised when the pi subprocess fails."""


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    # drop opening fence (``` or ```json)
    lines = lines[1:]
    # drop trailing fence
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


class PiAgentClient:
    """Run completions through the local pi agent subprocess."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def model_for_route(self, route: Route = "smart") -> str:
        return self.settings.llm_cheap_model if route == "cheap" else self.settings.llm_smart_model

    def _build_command(
        self,
        prompt: str,
        *,
        model: str,
        instructions: str | None,
        tools: Sequence[str] | None,
    ) -> list[str]:
        cmd: list[str] = [self.settings.pi_bin, "-p", "--mode", "text"]

        if self.settings.pi_provider:
            cmd += ["--provider", self.settings.pi_provider]
        if model:
            cmd += ["--model", model]
        if self.settings.pi_thinking:
            cmd += ["--thinking", self.settings.pi_thinking]

        # Keep startup quiet/cheap: no session files, no context discovery.
        cmd += ["--no-session", "--no-context-files"]

        # Tool control. Default: no tools at all. Otherwise an explicit allowlist.
        if tools:
            cmd += ["--tools", ",".join(tools)]
        else:
            cmd.append("--no-tools")

        if instructions:
            cmd += ["--append-system-prompt", instructions]

        # Prompt is the final positional argument.
        cmd.append(prompt)
        return cmd

    async def create_response(
        self,
        prompt: str,
        *,
        route: Route = "smart",
        model: str | None = None,
        instructions: str | None = None,
        json_schema: dict[str, Any] | None = None,
        tools: Sequence[str] | None = None,
        temperature: float | None = None,  # accepted for API compatibility; pi has no flag
        timeout: float | None = None,
    ) -> LLMResponse:
        selected_model = model or self.model_for_route(route)
        timeout = timeout or float(self.settings.pi_timeout_seconds)

        final_prompt = prompt
        if json_schema is not None:
            final_prompt = (
                f"{prompt}\n\n"
                "Respond with ONLY a single valid JSON object that conforms to this JSON schema. "
                "Do not wrap it in markdown code fences and do not add any commentary.\n"
                f"JSON schema:\n{_dump_schema(json_schema)}"
            )

        cmd = self._build_command(
            final_prompt,
            model=selected_model,
            instructions=instructions,
            tools=tools,
        )

        text = await self._run(cmd, timeout)
        if json_schema is not None:
            text = _strip_code_fences(text)
        return LLMResponse(text=text, model=selected_model, raw={"stdout": text})

    async def _run(self, cmd: list[str], timeout: float) -> str:
        if shutil.which(cmd[0]) is None:
            raise PiAgentError(
                f"pi binary '{cmd[0]}' not found on PATH; set PI_BIN or install the pi agent"
            )
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise PiAgentError(f"pi agent timed out after {timeout}s") from exc

        if proc.returncode != 0:
            raise PiAgentError(
                f"pi agent exited with code {proc.returncode}: {stderr.decode('utf-8', 'replace').strip()}"
            )
        return stdout.decode("utf-8", "replace").strip()


def _dump_schema(schema: dict[str, Any]) -> str:
    import json

    return json.dumps(schema, ensure_ascii=False)


def is_configured() -> bool:
    settings = get_settings()
    return shutil.which(settings.pi_bin) is not None
