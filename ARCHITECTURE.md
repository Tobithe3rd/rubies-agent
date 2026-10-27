# Rubies MFB Support Agent: Architecture

Capstone Project 1 (AI Engineering). Builder: Tobiloba Adeyemi. Brief: `AI_Engineering_Capstone_Project_Briefs.pdf` (project files).
Status: architecture locked; build not started.

## 1. Working agreement (read first in every chat)
- Build one step at a time. Give one step, wait for my confirmation, then give the next.
- Keep responses concise but complete enough to act on.
- The main project chat is the orchestrator. Build chats stay inside their scope.
- Do not change a locked decision without flagging it and updating this file.
- At the end of each chat, produce a short status note (what was built, file names, deviations) to paste into section 9.

### Building style (every build chat follows this)
- I build with **opencode** as the coding agent. Each step is delivered as a ready-to-paste **opencode prompt** (in a code block), not as code for me to type.
- Each opencode prompt must say: which files to create or edit, what to read first (e.g. `ARCHITECTURE.md`, the config files), the exact behaviour wanted, and what NOT to touch. It must respect the modularity rules in section 4 (no hardcoded choices; config and interfaces).
- Each step ends with a short **"Check it worked"** list: commands to run and what I should see.
- Anything I should do **myself** is marked **"YOU DO THIS"** and kept out of the opencode prompt. This includes: AWS account/credentials and Bedrock model access, editing `.env`, anything in a web console, decisions only I can make (e.g. Fleet details), running the app and reporting results, and reviewing generated code for security-sensitive parts (identity, confirmation, logging).
- When something fails, I paste the error or opencode output back, and the chat gives a corrective prompt.

## 2. System flow
Customer -> chat adapter (Fleet-facing) -> Strands agent on Bedrock -> tool wrapper (logs every call) -> mock bank API (FastAPI + SQLite) or RAG (ChromaDB)

## 3. Locked decisions
| Part | Decision |
|---|---|
| Agent | Strands + Amazon Bedrock, one agent, system prompt in `prompts/` |
| Mock bank API | FastAPI + SQLite, about 20 synthetic customers, 3 months of transactions each, audit table |
| Identity | Phone + OTP verification creates a session token. Agent injects it from session state. Tools take no `customer_id` argument. API re-checks the token on every call |
| Confirmation | `open_dispute` and `block_card` only propose and return a pending token. `confirm_action(token)` executes, only after a new user message arrives |
| RAG | 6-8 docs with numbered headings; chunk by heading/section (doc title + heading prepended); Bedrock Titan v2 embeddings; ChromaDB (local). Citation = document + section |
| No guessing | Similarity threshold, plus prompt rule: answer only from retrieved text, else say "I don't know" and offer handoff |
| Pidgin | System prompt rules + few-shot examples; reply in the user's register; rewrite query to plain English before retrieval |
| Handoff | Code triggers (user asks for human/manager, 2 failed retrievals, repeated tool errors, 3 failed verifications) + model judgement for upset users. Calls `handoff_to_human` with summary |
| Logging | Tool wrapper writes JSONL (time, session, tool, inputs, result/error) + audit table in the bank API |
| Fleet | OPEN: confirm how Fleet registers agents. Keep behind an adapter interface |

## 4. Modularity rules
1. Every choice and number lives in config, never in logic.
2. Every swappable part sits behind a small interface; config picks the implementation via a factory.
3. Prompts and few-shot examples are plain files.

| File | Controls |
|---|---|
| `.env` | Secrets/environment only: AWS region and credentials, bank API URL |
| `config/settings.yaml` | Model ID, embedding model, vector store type/path, chunking mode, similarity threshold, top-k, session expiry, handoff limits, log path, adapter, `debug` flag |
| `config/tools.yaml` | Per tool: enabled, `requires_confirmation`, `requires_verified_session`, description |
| `prompts/` | `system_prompt.md`, `pidgin_examples.md`, `handoff_summary.md`, `query_rewrite.md` |

Swappable behind interfaces: LLM provider, embedder, vector store, data store, interface adapter.
Debugging: `debug: true` gives verbose logs; startup prints which implementation each part loaded; config is validated at startup and fails fast with a clear message.

## 5. Repo layout
```
rubies-agent/
├── .env.example
├── config/        settings.yaml, tools.yaml
├── prompts/       *.md
├── core/          config loader, interfaces, factories
├── providers/     llm/, embeddings/, vectorstore/
├── bank_api/      main.py, models.py, seed.py
├── agent/         agent, tool wrapper, confirmation, handoff
├── rag/           docs/, ingest
├── adapters/      http_chat.py (Fleet adapter goes here)
├── data/  eval/  logs/
```

## 6. Tools
| Tool | Confirmation |
|---|---|
| verify_customer | No |
| get_balance | No |
| get_mini_statement | No |
| get_transaction_status | No |
| open_dispute | Yes |
| block_card | Yes |
| check_loan_eligibility | No |
| get_loan_status | No |
| handoff_to_human | No |
| search_policy (RAG) | No |

## 7. Ground rules from the brief
Synthetic data only (naira, Nigerian names/phone formats). At least 5 Pidgin test messages. Confirm before any state change. No guessing. Handoff with summary when unsure, user upset, or user asks. Log every tool call. Customer must never reach another customer's data.

## 8. Build order and chats
| Chat | Scope |
|---|---|
| 1. Foundation | Repo skeleton, config loader, interfaces, factories, startup validation, `/health` |
| 2. Bank API | FastAPI + SQLite, schema, 20 customers (incl. failed transfer, double debit, card holder, active loan), seed script, OTP/session |
| 3. Documents and RAG | The 6-8 policy docs, chunking, Titan, ChromaDB, citations, threshold |
| 4. Agent core | Strands agent, tool wrapper, session injection, two-step confirmation |
| 5. Behaviour | Pidgin prompts, handoff triggers, logging |
| 6. Fleet | Registration and adapter |
| 7. Eval and demo | 20-30 RAG questions, 10 tool scenarios, 5 safety cases, 7 demo scenarios, README |

Demo scenarios: (1) fee question with citation; (2) double debit -> verify, dispute after confirmation; (3) lost card -> verify, confirm, block; (4) N200,000 loan -> requirements + eligibility tool; (5) Pidgin "money no gree enter" -> ask reference, check status; (6) attack on neighbour's balance -> refuse, no tool call; (7) angry customer wants manager -> handoff with summary.

## 9. Status log (paste a note after each chat)
- Chat 1: DONE. Skeleton per section 5; core/config.py (pydantic, fail-fast ConfigError, masked summary), core/interfaces.py, core/factories.py (registry + lazy import map), core/startup.py, core/app.py (lifespan, /health), tests/ (15 passing). Python 3.12.
  Deviations: added tests/ folder; added core/startup.py and core/app.py; added startup.require_components (false until providers exist, then set true); added bank_api.store_type: sqlite; /health returns 200 ok/degraded, 503 error.
  Open for later chats: datastore import map points to providers/datastore/sqlite, which does not exist yet (decide in Chat 2 whether it lives there or in bank_api/); Fleet still OPEN (Chat 6); set llm.model_id in settings.yaml (currently CHANGE_ME) before Chat 4.
- - Chat 2: DONE. 90 tests passing.
  Built: SQLite DataStore in providers/datastore/sqlite.py (10 tables plus pending_actions; every customer-data method takes customer_id and filters by it; OTPs and session tokens stored hashed). bank_api/seed.py (20 synthetic customers, deterministic, dates relative to run day, balances derived from transactions) writing data/seed_manifest.md. bank_api/auth.py (phone + OTP, HMAC-SHA256 OTP hashes with OTP_HASH_SECRET, mock OTP delivery to logs/otp.log, 256-bit session tokens stored as SHA-256, lockout after max attempts, audit rows). bank_api/service.py and bank_api/main.py: protected routes for balance, statement, transaction status, loan eligibility (rule-based, config-driven) and loan status; dispute and card block are propose-then-confirm with single-use pending tokens bound to session and customer; POST /handoff works with or without a session. customer_id comes only from the session, never from path, query or body. scripts/check_step5.sh runs the live checks.
  Seeded scenarios (see data/seed_manifest.md): lost-card demo Adebayo Ogunleye (+2348031234567, last4 0001); failed transfer Fatima Ibrahim (RUB-03-000037, ₦50,000); double debit Bola Adeyemi (RUB-DB-001/002, ₦25,000); pending transfer Aisha Bello (RUB-07-000026, ₦15,000); active loan Tunde Afolabi; high inflow Chidi Adeyemi; low inflow Ngozi Okonkwo; new account Ngozi Afolabi; already-blocked card Chidi Nwankwo (9999).
  Deviations: DataStore lives in providers/datastore/sqlite.py (confirmed); added pending_actions table; added handoff_tickets.reason column; extra config (otp_delivery, otp_log_path, pending_action_ttl_seconds, mini_statement limits, eligibility block, handoff limits); added OTP_HASH_SECRET to .env; extra routes beyond the original scope (/auth/*, /me, /actions/confirm, /handoff).
  Notes for later: timestamps are naive local time, so settle one timezone convention before Chat 4/5; SQLite autoincrement IDs do not restart after reset_data, so eval expectations should match disputes by reference, not id; tools must send the session token from agent session state on every call; the agent-side half of two-step confirmation (a new user message must arrive before confirm_action) is Chat 4.
- Chat 3: not started
- Chat 4: not started
- Chat 5: not started
- Chat 6: not started
- Chat 7: not started
