import pytest
from core.config import AppConfig, ConfigError, load_config
from core import interfaces
from core import factories


class FakeEmbedder(interfaces.Embedder):
    def __init__(self, cfg, env):
        self._cfg = cfg
        self.dimensions = cfg.dimensions

    def describe(self):
        return f"fake_embedder:{self.dimensions}"

    def healthcheck(self):
        return interfaces.HealthStatus("fake_embedder", True, "ok")

    @property
    def dimensions(self) -> int:
        return getattr(self, "_dimensions", 128)
    @dimensions.setter
    def dimensions(self, value):
        self._dimensions = value

    def embed_documents(self, texts):
        return [[0.1] * self.dimensions for _ in texts]

    def embed_query(self, text):
        return [0.1] * self.dimensions


class FakeVectorStore(interfaces.VectorStore):
    def __init__(self, cfg, embedder, env):
        self.embedder = embedder
        self._cfg = cfg

    def describe(self):
        return "fake_vectorstore:fake"

    def healthcheck(self):
        return interfaces.HealthStatus("fake_vectorstore", True, "ok")

    def add(self, chunks, embeddings):
        pass

    def search(self, query_embedding, top_k):
        return []

    def count(self):
        return 0

    def reset(self):
        pass


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    # Save original registry and restore after test
    original = {k: dict(v) for k, v in factories._REGISTRY.items()}
    yield
    factories._REGISTRY.clear()
    for k, v in original.items():
        factories._REGISTRY[k] = dict(v)


class TestFactories:
    def test_fake_embedder_and_vectorstore_created_through_factory(self, monkeypatch):
        factories.register("embedder", "fake_embedder")(FakeEmbedder)
        factories.register("vectorstore", "fake_vectorstore")(FakeVectorStore)

        # We don't call full load_config; just test direct factory calls with a fake config
        from core.config import AppConfig, LLMConfig, EmbeddingsConfig, VectorstoreConfig, RAGConfig, SessionConfig, HandoffConfig, LoggingConfig, AdapterConfig, BankAPIConfig, EnvConfig, ToolsConfig
        import types

        # Register manually for this test
        factories.register("embedder", "fake_embedder")(FakeEmbedder)
        factories.register("vectorstore", "fake_vectorstore")(FakeVectorStore)

        # Load real config and monkeypatch provider names to fake ones
        cfg = load_config()
        cfg.settings.llm.provider = "fake_embedder"
        cfg.settings.embeddings.provider = "fake_embedder"
        cfg.settings.vectorstore.type = "fake_vectorstore"
        cfg.settings.adapter.type = "fake_adapter"
        cfg.settings.bank_api.store_type = "fake_datastore"
        # Monkeypatch dimensions to avoid validation issues
        # (fake_embedder will handle its own dimensions)

        # Register adapter and datastore too for completeness
        @factories.register("adapter", "fake_adapter")
        class FakeAdapter(interfaces.InterfaceAdapter):
            def describe(self): return "fake"
            def healthcheck(self): return interfaces.HealthStatus("fake", True, "ok")
            def start(self, handler): pass
            def stop(self): pass

        @factories.register("datastore", "fake_datastore")
        class FakeDataStore(interfaces.DataStore):
            def describe(self): return "fake"
            def healthcheck(self): return interfaces.HealthStatus("fake", True, "ok")
            def connect(self): pass
            def close(self): pass

        # Use direct factory calls to avoid full config dependency
        embedder = factories.create_embedder(cfg)
        assert isinstance(embedder, FakeEmbedder)
        vectorstore = factories.create_vectorstore(cfg, embedder)
        assert isinstance(vectorstore, FakeVectorStore)

    def test_unknown_name_raises_config_error_list_available(self, monkeypatch):
        class FakeLLMConfig:
            provider = "nonexistent_name_12345"
        class FakeCfg:
            settings = type("S", (), {"llm": FakeLLMConfig()})()
            env = type("E", (), {"AWS_REGION": "us-east-1", "BANK_API_URL": "http://localhost:8001", "AWS_ACCESS_KEY_ID": None, "AWS_SECRET_ACCESS_KEY": None, "AWS_SESSION_TOKEN": None})()
        with pytest.raises(ConfigError) as exc_info:
            factories.create_llm(FakeCfg())
        msg = str(exc_info.value)
        assert "Unknown" in msg or "not built yet" in msg or "Available" in msg

    def test_known_name_missing_module_raises_not_built_yet(self):
        # bedrock is in import map but module does not exist
        cfg = load_config()
        with pytest.raises(ConfigError) as exc_info:
            factories.create_llm(cfg)
        assert "not built yet" in str(exc_info.value)

    def test_real_default_config_raises_not_built_yet_for_each_kind(self):
        cfg = load_config()
        with pytest.raises(ConfigError) as exc_info:
            factories.create_llm(cfg)
        assert "not built yet" in str(exc_info.value)
        # embedder (titan) is now built
        assert factories.create_embedder(cfg) is not None
        # vectorstore (chroma) is now built
        embedder = factories.create_embedder(cfg)
        assert factories.create_vectorstore(cfg, embedder) is not None
        # datastore (sqlite) is now built, adapter is not
        with pytest.raises(ConfigError) as exc_info:
            factories.create_adapter(cfg)
        assert "not built yet" in str(exc_info.value)
