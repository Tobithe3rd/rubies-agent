from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from strands.models.model import Model

from core.factories import register
from core.interfaces import HealthStatus, LLMProvider


@dataclass
class ScriptContext:
    """Passed to callable script steps.

    `messages` is the history the agent sent to the model. `last_tool_result`
    is the full result envelope from the most recent tool call (`None` when no
    tool has run yet); `data` is convenience access to its `data` field.
    """

    messages: list
    last_tool_result: Optional[dict] = None

    @property
    def tool_result(self) -> Optional[dict]:
        return self.last_tool_result

    @property
    def data(self) -> Optional[dict]:
        if self.last_tool_result is None:
            return None
        return self.last_tool_result.get("data")


Step = tuple
Script = list


def _resolve(value: Any, ctx: ScriptContext) -> Any:
    return value(ctx) if callable(value) else value


class ScriptedLLM(Model):
    """A Strands `Model` driven by a fixed script, no network and no AWS.

    Implements the installed SDK's model interface so the real agent loop
    (tool calls and tool results included) runs exactly as with Bedrock.

    The script is a list with one entry per user turn; each entry is a list of
    steps. A step is either ``("tool", name, args_or_callable)`` or
    ``("text", reply_or_callable)``. Running out of steps raises a clear error
    naming the unmet step.
    """

    def __init__(self, scripts: Optional[list[Script]] = None, model_id: str = "mock"):
        self.scripts: list[Script] = list(scripts) if scripts else []
        self.model_id = model_id
        self.turn_index = 0
        self.step_index = 0
        self.call_count = 0
        self.last_tool_specs: Optional[list] = None
        self.last_messages: Optional[list] = None

    # --- script control ---

    def load_scripts(self, scripts: list[Script]) -> None:
        self.scripts = [list(turn) for turn in scripts]
        self.reset()

    def reset(self) -> None:
        self.turn_index = 0
        self.step_index = 0

    # --- Strands Model interface ---

    def update_config(self, **model_config: Any) -> None:
        if "model_id" in model_config:
            self.model_id = model_config["model_id"]

    def get_config(self) -> dict:
        return {"model_id": self.model_id}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("ScriptedLLM does not support structured output")
        yield  # pragma: no cover - makes this an async generator

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.call_count += 1
        self.last_tool_specs = tool_specs
        self.last_messages = messages

        if self._is_new_turn(messages):
            self.turn_index += 1
            self.step_index = 0

        if not self.scripts or self.turn_index < 1 or self.turn_index > len(self.scripts):
            raise RuntimeError(
                f"ScriptedLLM has no script for user turn {self.turn_index} "
                f"(unmet step {self.step_index})"
            )
        script = self.scripts[self.turn_index - 1]
        if self.step_index >= len(script):
            raise RuntimeError(
                f"ScriptedLLM ran out of steps in user turn {self.turn_index}: "
                f"unmet step {self.step_index}"
            )

        step = script[self.step_index]
        self.step_index += 1
        ctx = ScriptContext(messages=messages, last_tool_result=self._last_tool_result(messages))

        kind = step[0]
        if kind == "tool":
            name = step[1]
            args = _resolve(step[2], ctx)
            yield {"messageStart": {"role": "assistant"}}
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": str(uuid.uuid4()), "name": name}}
                }
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        elif kind == "text":
            reply = _resolve(step[1], ctx)
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockDelta": {"delta": {"text": reply}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        else:
            raise RuntimeError(
                f"ScriptedLLM does not understand step {self.step_index - 1} "
                f"in user turn {self.turn_index}: {kind!r}"
            )

    # --- helpers ---

    @staticmethod
    def _is_new_turn(messages) -> bool:
        if not messages:
            return True
        last = messages[-1]
        if last.get("role") != "user":
            return False
        return not any("toolResult" in block for block in last.get("content", []))

    @staticmethod
    def _last_tool_result(messages) -> Optional[dict]:
        for message in reversed(messages):
            for block in message.get("content", []):
                result = block.get("toolResult") if isinstance(block, dict) else None
                if not result:
                    continue
                for content in result.get("content", []):
                    if isinstance(content, dict) and "json" in content:
                        return content["json"]
                    if isinstance(content, dict) and "text" in content:
                        try:
                            return json.loads(content["text"])
                        except (TypeError, ValueError):
                            continue
        return None


@register("llm", "mock")
class MockLLM(LLMProvider):
    """LLM provider that returns the scripted model. Never touches AWS."""

    def __init__(self, cfg=None, env=None):
        self.cfg = cfg
        self.env = env
        self.model = ScriptedLLM()

    def describe(self) -> str:
        return "mock:scripted"

    def healthcheck(self) -> HealthStatus:
        return HealthStatus("mock", True, "scripted model ready")

    def get_model(self) -> ScriptedLLM:
        return self.model

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        # The agent path uses get_model(); this is only for the provider interface.
        return ""

    def load_scripts(self, scripts: list[Script]) -> None:
        self.model.load_scripts(scripts)
