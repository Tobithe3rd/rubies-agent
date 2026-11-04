from types import SimpleNamespace

from providers.llm.bedrock import BedrockLLM


def make_cfg(**overrides):
    values = dict(
        model_id="us.anthropic.claude-sonnet-4-6",
        temperature=0.2,
        max_tokens=1024,
        connect_timeout_seconds=5.0,
        read_timeout_seconds=60.0,
        max_attempts=3,
        retry_mode="standard",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_boto_client_config_sets_timeouts_and_retries():
    llm = BedrockLLM(make_cfg(), SimpleNamespace(AWS_REGION="us-east-1"))

    config = llm.boto_client_config()

    assert config.connect_timeout == 5.0
    assert config.read_timeout == 60.0
    assert config.retries["max_attempts"] == 3
    assert config.retries["mode"] == "standard"


def test_boto_client_config_is_overridable_from_config():
    llm = BedrockLLM(
        make_cfg(connect_timeout_seconds=2.0, max_attempts=5, retry_mode="adaptive"),
        SimpleNamespace(AWS_REGION="us-east-1"),
    )

    config = llm.boto_client_config()

    assert config.connect_timeout == 2.0
    assert config.retries["max_attempts"] == 5
    assert config.retries["mode"] == "adaptive"
