import pytest
from core.config import load_config, ConfigError
from agent.prompts import load_system_prompt


class TestPromptUpdates:
    def test_pidgin_examples_file_loads_and_appends(self):
        cfg = load_config()
        full = load_system_prompt(cfg)
        assert "## Register" in full
        assert "## Answering policy questions" in full
        assert "## No-guessing reminder" in full
        assert "Pidgin rules and examples" in full
        assert "bitcoin" in full
        assert "mortgage" in full
        assert "CEO" in full

    def test_missing_pidgin_file_raises_config_error(self):
        import tempfile, yaml, shutil
        from agent.prompts import load_system_prompt
        with tempfile.TemporaryDirectory() as td:
            shutil.copy("config/settings.yaml", td + "/settings.yaml")
            shutil.copy("config/tools.yaml", td + "/tools.yaml")
            with open(td + "/settings.yaml") as f:
                data = yaml.safe_load(f)
            data["agent"]["pidgin_examples_path"] = "prompts/nonexistent.md"
            with open(td + "/settings.yaml", "w") as f:
                yaml.safe_dump(data, f, sort_keys=False)
            cfg = load_config(config_dir=td)
            with pytest.raises(ConfigError) as exc_info:
                load_system_prompt(cfg)
            assert "agent.pidgin_examples_path" in str(exc_info.value)

    def test_query_rewrite_contains_new_examples(self):
        text = open("prompts/query_rewrite.md").read()
        assert "mortgage" in text
        assert "bitcoin" in text
        assert "CEO" in text
        assert "domiciliary dollar account" in text
