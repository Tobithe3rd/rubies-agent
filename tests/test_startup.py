import pytest
from core.startup import ComponentReport, StartupResult, run_startup
from core.config import ConfigError
from core import factories


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    original = {k: dict(v) for k, v in factories._REGISTRY.items()}
    yield
    factories._REGISTRY.clear()
    for k, v in original.items():
        factories._REGISTRY[k] = dict(v)


class FakeLLM:
    def __init__(self, cfg, env): pass
    def describe(self): return "fake_llm"
    def healthcheck(self):
        from core.interfaces import HealthStatus
        return HealthStatus("fake_llm", True, "ok")
    def get_model(self): return None
    def complete(self, prompt, system=None): return ""


class FakeEmbedder:
    def __init__(self, cfg, env): pass
    def describe(self): return "fake_embedder"
    def healthcheck(self):
        from core.interfaces import HealthStatus
        return HealthStatus("fake_embedder", True, "ok")
    @property
    def dimensions(self): return 128
    def embed_documents(self, texts): return [[0.0]*128 for _ in texts]
    def embed_query(self, text): return [0.0]*128


class FakeVectorStore:
    def __init__(self, cfg, embedder, env): pass
    def describe(self): return "fake_vectorstore"
    def healthcheck(self):
        from core.interfaces import HealthStatus
        return HealthStatus("fake_vectorstore", True, "ok")
    def add(self, chunks, embeddings): pass
    def search(self, query_embedding, top_k): return []
    def count(self): return 0
    def reset(self): pass


class FakeDataStore:
    def __init__(self, cfg, env): pass
    def describe(self): return "fake_datastore"
    def healthcheck(self):
        from core.interfaces import HealthStatus
        return HealthStatus("fake_datastore", True, "ok")
    def connect(self): pass
    def close(self): pass


class FakeAdapter:
    def __init__(self, cfg, env): pass
    def describe(self): return "fake_adapter"
    def healthcheck(self):
        from core.interfaces import HealthStatus
        return HealthStatus("fake_adapter", True, "ok")
    def start(self, handler): pass
    def stop(self): pass


class TestStartup:
    def test_all_fakes_healthy_overall_ok(self, monkeypatch):
        factories.register("llm", "fake_llm")(FakeLLM)
        factories.register("embedder", "fake_embedder")(FakeEmbedder)
        factories.register("vectorstore", "fake_vectorstore")(FakeVectorStore)
        factories.register("datastore", "fake_datastore")(FakeDataStore)
        factories.register("adapter", "fake_adapter")(FakeAdapter)

        from core.config import load_config
        cfg = load_config()
        cfg.settings.llm.provider = "fake_llm"
        cfg.settings.embeddings.provider = "fake_embedder"
        cfg.settings.vectorstore.type = "fake_vectorstore"
        cfg.settings.bank_api.store_type = "fake_datastore"
        cfg.settings.adapter.type = "fake_adapter"
        cfg.settings.startup.require_components = False

        # Monkeypatch config load inside run_startup
        monkeypatch.setattr("core.startup.load_config", lambda config_dir="config": cfg)

        res = run_startup()
        assert res.overall == "ok"
        assert len([r for r in res.reports if r.status == "loaded"]) == 5

    def test_default_config_all_components_built(self, monkeypatch):
        from core.config import load_config
        monkeypatch.setattr("core.startup.load_config", lambda config_dir="config": load_config())
        res = run_startup()
        assert res.overall == "ok"
        assert all(r.status == "loaded" for r in res.reports)

    def test_require_components_true_raises_config_error(self, monkeypatch):
        from core.config import load_config
        cfg = load_config()
        cfg.settings.startup.require_components = True
        # http_chat is still a placeholder with no module, so it is "not built"
        # and require_components must fail fast.
        cfg.settings.adapter.type = "http_chat"
        monkeypatch.setattr("core.startup.load_config", lambda config_dir="config": cfg)
        from core.app import create_app
        from fastapi.testclient import TestClient
        with pytest.raises(ConfigError):
            with TestClient(create_app()):
                pass

    def test_unhealthy_fake_overall_error(self, monkeypatch):
        class UnhealthyLLM:
            def describe(self): return "bad"
            def healthcheck(self):
                from core.interfaces import HealthStatus
                return HealthStatus("bad", False, "down")
            def get_model(self): return None
            def complete(self, prompt, system=None): return ""
        factories.register("llm", "bad_llm")(UnhealthyLLM)
        factories.register("embedder", "fake_embedder")(FakeEmbedder)
        factories.register("vectorstore", "fake_vectorstore")(FakeVectorStore)
        factories.register("datastore", "fake_datastore")(FakeDataStore)
        factories.register("adapter", "fake_adapter")(FakeAdapter)

        from core.config import load_config
        cfg = load_config()
        cfg.settings.llm.provider = "bad_llm"
        cfg.settings.embeddings.provider = "fake_embedder"
        cfg.settings.vectorstore.type = "fake_vectorstore"
        cfg.settings.bank_api.store_type = "fake_datastore"
        cfg.settings.adapter.type = "fake_adapter"
        cfg.settings.startup.require_components = False
        monkeypatch.setattr("core.startup.load_config", lambda config_dir="config": cfg)
        res = run_startup()
        assert res.overall == "error"
        assert any(r.kind == "llm" and r.healthy is False for r in res.reports)
