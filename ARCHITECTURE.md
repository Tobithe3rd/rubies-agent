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
- - Chat 3: DONE. pytest passing (at least 125 tests); scripts/check_rag_all.sh passes 24/24 live (LIVE=0 for offline).
  Built: 8 documents in rag/docs/ (RUB-DOC-01 fee schedule, 02 account types and KYC tiers, 03 transfers and failed transactions, 04 disputes and complaints, 05 cards/USSD/app, 06 loans, 07 fraud and security, 08 general FAQ), 75 numbered sections. rag/facts.yaml is the single source of truth for figures (derived from config and the seeded DB, plus scenarios, fictional_bank, real_rules, doc_examples); rag/sources.md registers the real rules. rag/chunker.py (heading mode) writes data/rag_chunks.jsonl: 75 chunks, id RUB-DOC-0N#<section>, citation "<doc title>, section N (<heading>)", title and heading prepended to the text. providers/embeddings/titan.py (amazon.titan-embed-text-v2:0, 1024 dims, normalized) and mock.py; providers/vectorstore/chroma.py (persistent, cosine, telemetry off, embedder-signature mismatch guard); rag/ingest.py; rag/calibrate.py; rag/search.py; rag/threshold_report.py; rag/analyze_dev_set.py; eval/rag_dev_set.yaml (20 in-scope + 6 out-of-scope tuning set, NOT the held-out eval); rag/README.md.
  search_policy(query) returns PolicySearchResult(status ok | no_relevant_result | invalid_query, query, results[chunk_id, citation, doc_title, section_heading, text, score], top_score, threshold, message). Infrastructure errors (Bedrock, store) propagate as typed errors; no-match never raises.
  Config (settings.yaml rag.*): docs_dir, ignore_prefixes, chunking (mode heading, max_words 450), chunks_path, top_k 4, similarity_threshold 0.35, max_query_chars 1000, no_result_message, embedding (titan, model id, 1024, normalize, max_retries, backoff, timeout), vector_store (chroma, data/chroma, rubies_policy). Run python -m rag.ingest after any document change; data/chroma is gitignored.
  Calibration: lowest in-scope top-1 score 0.4924; clearly off-topic 0.10-0.13; dev set at 0.35: in-scope refused 0/20, off-topic answered 0/3, recall@4 19/20, top-1 10/20 (6 of the 10 rank-1 misses are outranked by the FAQ doc 08).
  Deviations: Step 3b changed bank_api/seed.py so each customer's KYC tier is the lowest tier whose max balance fits the balance (12 customers raised; no balance exceeds a tier cap), seed_manifest regenerated, tests added; scripts/check_rag_step3.sh has an ALLOW_SEED_CHANGE flag; added boto3 and chromadb dependencies; extra modules beyond the plan (calibrate, threshold_report, analyze_dev_set, facts.yaml, sources.md).
  Unconfirmed inputs: KYC tier limits (T1 NGN 50,000 daily / 300,000 max balance; T2 200,000 / 500,000; T3 5,000,000 / no limit) come from secondary sources citing CBN circulars FPR/DIR/CIR/GEN/02/001 (2013) and BPS/DIR/GEN/CIR/04/007 (2017), not confirmed against the official CBN text. Transfer fee bands (NGN 10 / 25 / 50 plus 7.5% VAT) not confirmed against the CBN Guide to Charges. All real rules read 2026-10-27 and may be out of date.
  Open for later chats:
  - Chat 4: wrap search_policy as a tool; the wrapper logs status, top_score and threshold (not the query text at info level); count no_relevant_result toward the "2 failed retrievals" handoff trigger; handle Bedrock/store errors as tool errors. llm.model_id in settings.yaml is still CHANGE_ME.
  - Chat 5: prompt rule "answer only from retrieved text, else say I do not know and offer handoff". KNOWN LIMITATION: in-domain questions the docs do not answer ("Can I buy bitcoin with my Rubies account?", "Who is the CEO of Rubies?") still score about 0.516 against RUB-DOC-08#1, so the threshold cannot refuse them (2 of 3 answered at 0.35); the prompt rule must cover them. Tell the agent to cite the topic document rather than the FAQ when both contain the answer. Re-run python -m rag.threshold_report on Pidgin-rewritten queries and re-check the threshold.
  - Chat 7: the held-out RAG eval set must be new (not the dev set), include the in-domain unanswerable cases, and match expected sources on the answer-bearing chunk. Known gap: "What are the requirements for a Rubies loan?" ranks RUB-DOC-06#6 first and RUB-DOC-06#4 (eligibility thresholds) outside the top 4; consider rag.top_k 6 or a document tweak.
  - Fleet still OPEN (Chat 6). Timestamp convention note from Chat 2 still applies to Chats 4 and 5.
- Chat 4: not started
- Chat 5: not started
- Chat 6: not started
- Chat 7: not started
