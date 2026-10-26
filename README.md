# Rubies MFB Support Agent

AI support agent for MFB customers: verified identity, RAG policy lookup, mock bank API integration, Pidgin-aware responses, confirmation-gated actions, and structured handoff.

Status: Foundation complete (Chat 1). Providers, bank API, RAG, agent core, Fleet adapter and evaluation are still to come.

## Setup

Requires Python 3.11+ (built and tested on 3.12). Create a virtual environment, install dependencies, and set secrets:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (optional: AWS_SESSION_TOKEN), BANK_API_URL
```

AWS region and credentials are needed from Chat 3 onward (Bedrock LLM and embeddings). Until then the skeleton runs without them, but `/health` will show `degraded` with `not_built` components.

## Architecture

System flow (ARCHITECTURE.md §2):
Customer → chat adapter (Fleet-facing) → Strands agent on Bedrock → tool wrapper → mock bank API or RAG.

Five swappable parts (modularity rules §4):

| Part | Config file | Implementation directory |
|---|---|---|
| LLM provider | `config/settings.yaml` → `llm.provider` | `providers/llm/` |
| Embedder | `config/settings.yaml` → `embeddings.provider` | `providers/embeddings/` |
| Vector store | `config/settings.yaml` → `vectorstore.type` | `providers/vectorstore/` |
| Data store (bank API) | `config/settings.yaml` → `bank_api.store_type` | `providers/datastore/` (not built yet) |
| Adapter (chat interface) | `config/settings.yaml` → `adapter.type` | `adapters/` |

Every choice lives in config, never in logic. Each part is selected by a factory (`core/factories.py`) that reads the config name and loads the registered implementation.

## Configuration

- `.env`: secrets and environment only (`AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, optional `AWS_SESSION_TOKEN`, `BANK_API_URL`). Nothing else goes here.
- `config/settings.yaml`: all non-secret settings — model IDs, chunking mode, similarity threshold (`similarity_threshold: 0.35`), `top_k`, session expiry, adapter host/port (`port: 8000`), `startup.require_components` (set `true` once all providers exist), `debug` flag, `bank_api.db_path`.
- `config/tools.yaml`: per-tool switches (`enabled`, `requires_confirmation`, `requires_verified_session`, `description`).
- `prompts/`: `system_prompt.md`, `pidgin_examples.md`, `handoff_summary.md`, `query_rewrite.md` (to be filled in Chat 5+).

`startup.require_components` controls fail-fast: when `false` (current), unbuilt components are reported as `degraded` so `/health` stays available; when `true`, a missing provider raises `ConfigError` and the process exits.

`debug: true` enables verbose `rubies` logger output and prints the masked config summary at startup.

## How to run

```bash
python -m core.app
```

Check health:
```bash
curl -s localhost:8000/health | python -m json.tool
```

Run tests:
```bash
pytest -q
```

Expected `/health` response today: `{"status":"degraded","components":[...],"debug":false}` with `not_built` entries for `bedrock`, `chroma`, etc. This is expected — the providers are not yet built.

## Evaluation

(To be filled in Chat 7: 20-30 RAG questions, 10 tool scenarios, 5 safety cases, 7 demo scenarios, full README update.)
