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
| Web interface | HTTP web adapter beside the CLI (same agent), not a second agent. The web UI is not a capstone deliverable |
| Web session | One in-memory AgentRunner + transcript per chat; 15-minute idle limit; browser keeps only the chat id in `sessionStorage`; nothing on disk |
| Fleet | OPEN: confirm how Fleet registers agents. Keep behind an adapter interface |

## 4. Modularity rules
1. Every choice and number lives in config, never in logic.
2. Every swappable part sits behind a small interface; config picks the implementation via a factory.
3. Prompts and few-shot examples are plain files.
4. Web module files (web/, adapters/web*, their tests) stay at or under 250 non-blank, non-comment lines (config/quality.yaml). Enforced by scripts/checks/check_web_file_size.py and ESLint max-lines. Generated code (web/components/ui, web/components/ai-elements) is exempt.

| File | Controls |
|---|---|
| `.env` | Secrets/environment only: AWS region and credentials, bank API URL |
| `config/settings.yaml` | Model ID, embedding model, vector store type/path, chunking mode, similarity threshold, top-k, session expiry, handoff limits, log path, adapter, `debug` flag |
| `config/tools.yaml` | Per tool: enabled, `requires_confirmation`, `requires_verified_session`, description |
| `config/quality.yaml` | Web module file-size limit, included globs and generated-code exemptions |
| `prompts/` | `system_prompt.md`, `pidgin_examples.md`, `handoff_summary.md`, `query_rewrite.md` |

Swappable behind interfaces: LLM provider, embedder, vector store, data store, interface adapter.
Debugging: `debug: true` gives verbose logs; startup prints which implementation each part loaded; config is validated at startup and fails fast with a clear message.

## 5. Repo layout (reorganised after Chat 5 Step 3; Phase 3 code moves deferred)
```
rubies-agent/
├── README.md  ARCHITECTURE.md  requirements.txt  .env.example  .gitignore
├── config/        settings.yaml, tools.yaml, quality.yaml   (all swapping and tuning)
├── prompts/       system_prompt.md, query_rewrite.md (+ pidgin_examples.md, handoff_summary.md planned)
├── core/          config, interfaces, factories, clock, startup, app.py (to move to adapters/ later)
├── providers/     datastore/, embeddings/, llm/, otp/, vectorstore/
├── bank_api/      main.py, auth.py, service.py, seed.py
├── agent/         runner, session, errors, prompts, bank_client, tool_specs, tool_runtime, strands_tools, tool_logger
├── rag/           docs/, facts.yaml, sources.md, ingest, chunker, search, query_rewrite
│                  (dev tools to move to eval/ later: calibrate, analyze_dev_set, threshold_report)
├── adapters/      cli_chat.py, web/ (package), web_chat.py (thin shim; Fleet adapter goes here)
├── web/           Next.js frontend: app/, core/, features/, components/ui, components/ai-elements
├── contract/      event and history fixtures shared by backend and frontend tests
├── eval/          datasets/ (rag_dev_set, pidgin_tuning_set), reports/ (calibration, threshold reports)
├── scripts/       servers.sh; checks/ (acceptance and regression check scripts)
├── tests/         mirrors the code: agent/ bank_api/ rag/ core/ providers/ adapters/
├── data/          runtime/ (bank.db, chroma/: gitignored), generated/ (rag_chunks.jsonl, seed_manifest.md)
├── logs/          tool_calls.jsonl, otp.log
└── docs/brief/    capstone brief PDF
```
Where to look: agent behaviour in `agent/`, swappable parts in `providers/`, config in `config/`, policy documents in `rag/docs/`, anything measured in `eval/`, anything generated or stored in `data/`.

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
| 6. Web interface (done) and Fleet registration (open) | HTTP web adapter and Next.js frontend; Fleet registration is blocked until access is granted |
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
- - Chat 4: DONE. 234 tests passing. Per-step scripts: scripts/check_chat4_step1.sh to check_chat4_step5.sh (each re-runs the earlier ones; LIVE=0 SKIPs AWS checks). Live acceptance (check_chat4_step5.sh LIVE=1) passed twice in a row, every scenario on attempt 1 of 2.
  Built: core/clock.py (single clock; timezone convention in settings). agent/session.py (SessionState: turn counter, pending confirmations, counters failed_retrievals, consecutive_failed_retrievals, tool_error_count, failed_verifications; token never in repr). core/interfaces.py BankGateway + agent/bank_client.py (HttpBankGateway, Bearer token only in the header, no retries on propose/confirm) + agent/errors.py (BankUnauthorized, BankNotFound, BankRejected, BankUnavailable). agent/tool_specs.py (allowed arguments per tool; none takes customer_id or token), agent/tool_runtime.py (ToolRuntime.call: schema check, verified-session check, token from session state, confirm_action guard before any gateway call, never raises), agent/tool_logger.py (JSONL: time, session_id, tool, inputs, ok, result/error, duration_ms; redaction by config). providers/llm/bedrock.py and mock.py (ScriptedLLM), agent/prompts.py, prompts/system_prompt.md (baseline), agent/strands_tools.py (adapters, per-turn tool cap), agent/runner.py (AgentRunner: start_turn once per non-empty message; model/SDK errors become agent_error log line + fallback message). adapters/cli_chat.py (python -m adapters.cli_chat; commands /new /otp /help /quit).
  Timezone convention: Africa/Lagos wall time (UTC+1, no DST). SQLite timestamps stay naive local (Chat 2 code still uses datetime.now; correct only while the machine is on Lagos time); logs and new code use core/clock.py with +01:00 offset.
  Config added: timezone; agent.{system_prompt_path, max_history_messages, tool_timeout_seconds, bank_api_timeout_seconds, max_tool_calls_per_turn, fallback_message}; llm.{provider, temperature, max_tokens}; logging.{tool_log_path, redact_keys, mask_phone_keep_last, pending_token_prefix_chars}; handoff.{max_failed_retrievals 2, max_failed_verifications 3} (validated, NOT yet used); adapters.cli.{allow_otp_command, prompt_text, agent_label}; acceptance.max_attempts_per_scenario; bank_api.gateway. llm.model_id is a Bedrock inference profile ID (the plain model ID is rejected for on-demand use).
  Additions to the plan (flag): confirm_action (11 tools, section 6 lists 10); CLI adapter; BankGateway as a swappable part (not in section 4 table); per-turn tool-call cap; agent_error log line.
  Deviations: tests/test_seed_tiers.py now asserts the tier rule instead of a frozen snapshot (seed balances and tiers shift with the run day); agent/tool_runtime.py logs search_policy top result (chunk id, citation, text) so acceptance checks can compare it; config/tools.yaml get_mini_statement description rewritten (it told the model to ask how many first); prompt gained a "Common problems" section and a propose-then-ask-then-confirm rule.
  Proven on real files (SQLite, JSONL log): double debit (verify, find both, propose, confirm only on the next turn: one dispute for RUB-DB-002, ₦25,000), lost card (verify, last4, propose, confirm, card blocked), loan (search_policy + check_loan_eligibility equal to the direct API result), Pidgin verification path (Fatima, RUB-03-000037 failed ₦50,000), neighbour attack (no tool call; no cross-customer data in the log), same-turn confirm bypass refused (confirmation_not_allowed), argument injection (customer_id, token) refused, tokens and OTPs absent from the log.
  Notes for later:
  - Chat 5: handoff triggers (counters and limits exist, no logic yet); Pidgin few-shot and query rewriting; prompts/pidgin_examples.md, handoff_summary.md, query_rewrite.md do not exist; re-run python -m rag.threshold_report on rewritten queries. Verify and harden logging: redact_keys only covers listed key names (add any new secret-bearing argument); decide whether search_policy's top_result text should be gated by config. Scenario 7 (angry customer, handoff with summary) is not yet tested live.
  - Known limits: code proves a new user message arrived before confirm_action, not that it said yes (the prompt covers that; consider a code-side yes check). No tool lists a customer's cards, so the customer must give the last 4 digits (bank API change if wanted). Policy answers on in-domain unanswerable questions still depend on the prompt rule (Chat 3 note). The live scenarios are wording-sensitive in two places (scenario 1 citation and naira figure, scenario 2 "25,000"); the real model is non-deterministic, so re-run twice after any prompt change.
  - Chat 7: eval must match customers by name, phone, reference and amount only (tiers and dates shift per run; dispute ids do not reset). pytest regenerates data/seed_manifest.md, so discard it before commits.
  - Chat 6: Fleet adapter goes beside adapters/cli_chat.py via the existing adapter factory; Fleet still OPEN.
- Chat 5 steps 1-4 (28 Oct to 2 Nov 2026):
- Step 1 design decisions: query rewriting = a separate small LLM call inside the search_policy path (option A; falls back to the original query on any failure). Handoff enforcement = hybrid (see NEXT STEP).
- Step 2 DONE: QueryRewriter interface + RewriteResult (core/interfaces.py); rag/query_rewrite.py (LLM and passthrough); prompts/query_rewrite.md; rag.query_rewrite config block (timeout_seconds 45, log_text false); rewrite happens in agent/strands_tools.py before search; one JSONL "query_rewrite" event per rewrite, no query text at info level.
- Step 3 DONE: eval/datasets/pidgin_tuning_set.yaml (14 in-scope, 3 off-topic, 2 unanswerable_in_domain; a TUNING set, not the Chat 7 held-out eval); rag/threshold_report.py extended (--queries, --rewrite on|off, --output, config-driven sweep via rag.threshold_report). Threshold 0.35 and top_k 4 unchanged.
- Step 4 DONE and verified: prompts/pidgin_examples.md (examples show the tool step before any claim; square-bracket lines are never printed), prompts/system_prompt.md (appended sections: Register, Answering policy questions, No-guessing reminder, "Never claim an action you did not perform"), prompts/query_rewrite.md tightened (never swap or generalise product words), config agent.pidgin_examples_path, agent/prompts.py appends the examples. Commit 6792247.
  Verification: scripts/checks/live_step4.sh/.py (Pidgin P1-P5, no-guessing N1-N3) 8/8 twice; scripts/checks/live_retrieval_gates.sh/.py 12/0 twice; Chat 4 live acceptance (scripts/checks/check_chat4_step5.sh with LIVE=1) 14/0 twice with the new prompts; pytest 265 passing.
  Retrieval (rewrite on): Pidgin set 0/14 refused, 0/3 off-topic answered, recall@4 13/14, lowest in-scope top-1 0.4233 (margin 0.0733 over 0.35); plain-English dev set 0/20 refused, 0/3 off-topic answered (the mortgage regression from Step 3 is gone), recall 19/20, lowest 0.4654. KNOWN LIMIT unchanged: in-domain unanswerable questions (bitcoin 0.5415, owner 0.5226, both vs RUB-DOC-08#1) cannot be refused by the threshold; the prompt rule handles them (N1 and N2 pass).
Repairs made along the way (all committed except where noted):
- The layout refactor (tags layout-phase2) broke the old check scripts. Fixed with shared libs scripts/checks/lib_manifest.sh (manifest_check: tolerates dates, KYC tiers, monthly inflow, sequential reference numbers RUB-NN-NNNNNN and the Transactions count; strict on names, phones, scenario amounts, last4, fixed refs like RUB-DB-001, other counts; handles the manifest path at chat3-done data/seed_manifest.md vs data/generated/seed_manifest.md) and scripts/checks/lib_protected.sh (protected_check; agent/session.py, agent/bank_client.py, agent/errors.py, agent/tool_runtime.py strictly unchanged; bank_api/seed.py allowed if manifest-path-only OR byte-identical to tag seed-fix-reviewed). Self-tests: test_lib_manifest.sh (24 cases), test_lib_protected.sh (15 cases). check_chat4_step4/5 and check_chat5_step2/3 call them.
- Seed bug fixed (bank_api/seed.py): on the 1st to 4th of a month the "5th of each of the last 3 months" salary loop skipped the current month, giving 2 credits instead of 3 (inflow, transaction count and reference numbers shifted; it would also have changed the demo's loan eligibility). Fix: start from the previous month if this month's 5th has not happened. main(today=None, manifest_path=None); seed tests now write a temp manifest; new regression test. Tag seed-fix-reviewed.
- Tags: chat3-done, chat4-done, layout-phase2, seed-fix-reviewed.
Config already present and unused: handoff.max_failed_retrievals 2, handoff.max_failed_verifications 3 (validated). SessionState counts failed_retrievals, consecutive_failed_retrievals, tool_error_count, failed_verifications. Tool handoff_to_human and POST /handoff already exist (work with or without a session; handoff_tickets table has a reason column). prompts/handoff_summary.md does not exist yet. Verify whether handoff.handoff_summary_max_chars exists before building.

- Layout refactor (29-30 Oct 2026): Phases 1-2 done (data/eval/scripts/docs moved, tests mirrored). Scripts now run as scripts/checks/<name>.sh. Phase 3 (moving agent/rag/core code, import rewrites) deferred until after the first demo.
- Chat 6a: Web interface (3 to 4 Nov 2026).
  Built: web adapter package `adapters/web/` (`adapters/web_chat.py` is a thin shim; run with `python -m uvicorn adapters.web_chat:create_app --factory --port 8002`). Routes: `POST /chats`; `POST /chats/{id}/messages` (JSON); `POST /chats/{id}/messages/stream` (SSE events step, text, panel, done, error); `GET /chats/{id}/session`; `GET /chats/{id}/history`; `GET /chats/{id}/dev-otp` (config-gated; committed config has `allow_dev_otp: false`); `DELETE /chats/{id}`; `GET /health`. `chat_id` comes only from `secrets.token_urlsafe(32)`.
  Session model: one AgentRunner and SessionState per chat, in memory; idle limit 900 s, max age 3600 s, verification expiry clears the chat (`clear_transcript_on_verification_expiry`); transcript kept in memory only, never on disk or in logs; browser stores only the chat id in `sessionStorage` (`web/core/storage/chat-id-store.ts`). Chats do not survive a server restart.
  Customer-facing tool steps: plain-English labels per tool in `config/tools.yaml` (running, done, failed, awaiting, no_action). Adapter-built stream events carry only labels, citations and allow-listed receipt fields; history redacts tokens, OTPs and phone numbers. Live model text deltas are streamed as-is and scrubbed only when history is read. Panel receipts (dispute reference, card block last4, handoff ticket) are built from an allow-list of result fields.
  Hooks added in `agent/` (protected files untouched): `AgentRunner._setup_turn` and `stream_events`; tool observer and result observer in `agent/strands_tools.py` wired in `agent/runner.py`. `cli_chat.py` now streams through `AgentRunner.stream_events` (historical note: the CLI streaming path used to skip `start_turn`, so `confirm_action` was always refused as same-turn — unverified, historical).
  Also changed: bank API validates and normalises Nigerian phone numbers (`bank_api.phone_pattern`; 422 `invalid_phone_format`); unknown but well-formed numbers get the same response as known ones (anti-enumeration), and the agent says a code is sent only if the number is registered; prompts and Pidgin examples updated. Bedrock connect/read timeouts and retries are configured under `llm` in `settings.yaml`.
  Frontend: `web/` is Next.js 16 with shadcn/ui and AI Elements components copied as source (the AI Elements CLI is deprecated from end of Nov 2026 per `web/README`; unverified externally; the components are unaffected). Structure: `core/` (contract, transport interface with http and mock implementations, config, pure reducer, storage), `features/chat`, `features/panel`, `app/` (composition). Boundaries enforced by ESLint; feature folders cannot import each other. `NEXT_PUBLIC_TRANSPORT=mock` runs the UI with no backend. The event and history contract is defined once (`web/core/contract.ts`) and checked against `contract/` fixtures by a Vitest test and `tests/adapters/test_web_contract_fixtures.py`.
  Deviations: did not fork `vercel/ai-chatbot` (too heavy: auth, database, blob storage; flagged to and approved by the builder — unverified from the repo); Magic UI used for at most three subtle accents (unverified — no trace found in the repo); `DESIGN.md` and `PRODUCT.md` were not created by `/impeccable init` (both absent).
  Tests: pytest 387 passing; Vitest 24 passing; ESLint and the size check pass.
  Open: Fleet registration (Chat 6b); full live card, dispute and handoff walk-through through the refactored frontend to be confirmed; re-run the wording-sensitive live acceptance twice (`scripts/checks/check_chat4_step5.sh` with `LIVE=1`) after the phone-validation prompt change.
  Notes for later: the web adapter is the natural base for the Fleet adapter if Fleet needs an HTTP endpoint; the chat 7 evaluation set must not depend on dates or tiers (see the earlier note).
- Chat 6b: Fleet: not started (blocked on access)
- Chat 7: not started
