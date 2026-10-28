import pytest
from core.app import create_app
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


class TestHealth:
    def test_all_fakes_health_200(self, monkeypatch):
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
        monkeypatch.setattr("core.startup.load_config", lambda config_dir="config": cfg)

        from fastapi.testclient import TestClient
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "components" in data
            assert data.get("debug") == False
            # No secrets
            assert "AWS_ACCESS_KEY_ID" not in str(data)
            assert "secret" not in str(data)

    def test_default_config_ok_200(self, monkeypatch):
        from core.config import load_config
        monkeypatch.setattr("core.startup.load_config", lambda config_dir="config": load_config())
        from fastapi.testclient import TestClient
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert all(c["status"] == "loaded" for c in data["components"])
