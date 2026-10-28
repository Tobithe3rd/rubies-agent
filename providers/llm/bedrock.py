from __future__ import annotations

from core.config import ConfigError
from core.factories import register
from core.interfaces import HealthStatus, LLMProvider


@register("llm", "bedrock")
class BedrockLLM(LLMProvider):
    """Amazon Bedrock LLM behind the Strands Agent, built from config.

    Uses the installed Strands SDK's BedrockModel. Region comes from the
    environment (AWS_REGION); model id, temperature and max_tokens from
    settings.llm. A CHANGE_ME model id fails fast here, naming the key.
    """

    def __init__(self, cfg, env):
        self.cfg = cfg
        self.env = env
        self.model_id = cfg.model_id
        self.temperature = cfg.temperature
        self.max_tokens = cfg.max_tokens
        self.region = getattr(env, "AWS_REGION", "") or ""
        if not self.model_id or self.model_id == "CHANGE_ME":
            raise ConfigError(
                "llm.model_id is still CHANGE_ME: set a Bedrock model id in "
                "config/settings.yaml"
            )
        self._model = None

    def describe(self) -> str:
        return f"bedrock:{self.model_id}"

    def healthcheck(self) -> HealthStatus:
        if not self.region:
            return HealthStatus(self.describe(), False, "AWS_REGION is not set")
        # Construction is lazy; no network call is made here.
        return HealthStatus(self.describe(), True, "configured")

    def get_model(self):
        if self._model is None:
            from strands.models import BedrockModel

            self._model = BedrockModel(
                model_id=self.model_id,
                region_name=self.region,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        return self._model

    def complete(
        self,
        prompt: str,
        system=None,
        temperature=None,
        max_tokens=None,
    ) -> str:
        from strands import Agent
        from strands.models import BedrockModel

        if temperature is None and max_tokens is None:
            model = self.get_model()
        else:
            model = BedrockModel(
                model_id=self.model_id,
                region_name=self.region,
                temperature=self.temperature if temperature is None else temperature,
                max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            )
        agent = Agent(
            model=model,
            system_prompt=system,
            callback_handler=None,
            name="rubies-complete",
        )
        return str(agent(prompt))
