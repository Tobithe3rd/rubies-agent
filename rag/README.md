# RAG README

## Overview

This folder holds the retrieval-augmented generation (RAG) layer for the Rubies MFB Support Agent. It turns the eight policy documents in `rag/docs/` into heading chunks, embeds them with Amazon Bedrock Titan v2, stores them in a local ChromaDB collection, and answers policy questions with citations through `search_policy`. All figures used by the documents and by the code come from one place: `rag/facts.yaml`.

## Documents

The corpus is eight policy documents, chunked by heading. Document IDs and titles below are read from `data/rag_chunks.jsonl`.

| Document ID | Title | File |
|---|---|---|
| RUB-DOC-01 | Fee Schedule | rag/docs/01_fee_schedule.md |
| RUB-DOC-02 | Account Types and KYC Tiers | rag/docs/02_account_types_and_kyc.md |
| RUB-DOC-03 | Transfers and Failed Transactions | rag/docs/03_transfers_and_failed_transactions.md |
| RUB-DOC-04 | Disputes and Complaints Procedure | rag/docs/04_disputes_and_complaints.md |
| RUB-DOC-05 | Cards, USSD and App Guide | rag/docs/05_cards_ussd_app.md |
| RUB-DOC-06 | Loan Products and Requirements | rag/docs/06_loans.md |
| RUB-DOC-07 | Fraud and Security | rag/docs/07_fraud_and_security.md |
| RUB-DOC-08 | General FAQ | rag/docs/08_general_faq.md |

`rag/facts.yaml` is the single source of truth for every figure (fees, limits, timelines, eligibility thresholds and scenario amounts); the documents and the checks read from it rather than retyping numbers.

## Pipeline

**Documents.** The eight Markdown files in `rag/docs/` are the corpus. Each has a `#` title, a `Document ID:` metadata line, and `## N. Heading` sections.

**Chunking.** `rag/chunker.py` splits each document into one chunk per `## N. Heading` section (subsections stay inside their parent), prepends `<title> > <N>. <heading>` to the body, and writes `data/rag_chunks.jsonl`. A section longer than `chunking.max_words` is split on paragraph boundaries and the parts share one citation.

**Embeddings.** `providers/embeddings/titan.py` calls Amazon Bedrock Titan v2 (`invoke_model`) one text per call, using the model id, dimensions and normalise flag from config. `providers/embeddings/mock.py` is a deterministic offline stand-in used by tests and offline checks.

**Store.** `providers/vectorstore/chroma.py` keeps a persistent ChromaDB collection at the configured path with cosine space and telemetry disabled. Embeddings are always supplied by our embedder; Chroma's own embedding function is never used. Collection metadata records the embedder signature so a mismatched embedder is refused.

**Search.** `rag/search.py` exposes `search_policy(query)`, which embeds the query, retrieves `top_k` neighbours, applies `similarity_threshold`, and returns a `PolicySearchResult` with citations, or an explicit no-result status.

## Configuration

Every `rag.*` key is read from `config/settings.yaml` (values shown are the current ones):

| Key | Value |
|---|---|
| `rag.docs_path` | rag/docs |
| `rag.chunking_mode` | heading |
| `rag.chunking.mode` | heading |
| `rag.chunking.max_words` | 450 |
| `rag.ignore_prefixes` | ["_"] |
| `rag.chunks_path` | data/rag_chunks.jsonl |
| `rag.top_k` | 4 |
| `rag.similarity_threshold` | 0.35 |
| `rag.max_failed_retrievals` | 2 |
| `rag.max_query_chars` | 1000 |
| `rag.no_result_message` | No relevant policy information was found. Do not guess. Tell the customer you do not know and offer a human handoff. |

Swappable parts and the interface each sits behind: the LLM behind `LLMProvider`, the embedder behind `Embedder`, the vector store behind `VectorStore`, the bank data store behind `DataStore`, and the chat adapter behind `InterfaceAdapter`. Config picks the implementation and `core/factories.py` builds it.

## Running it

```bash
python -m rag.chunker            # chunk the documents into data/rag_chunks.jsonl
python -m rag.ingest             # embed and (re)build the Chroma collection
python -m rag.calibrate          # record retrieval scores for the 11 calibration questions
python -m rag.threshold_report   # score the 26-question dev set across candidate thresholds
python -m rag.analyze_dev_set    # explain the dev-set misses from the threshold report
bash scripts/check_rag_all.sh    # run the whole RAG check suite
```

Add `LIVE=0` for the offline path, for example `LIVE=0 bash scripts/check_rag_all.sh`. `python -m rag.ingest --config <dir>` and the other commands accept an alternative config directory.

## Citations and no-guessing

`search_policy` returns a `status` of `ok`, `no_relevant_result` or `invalid_query`. On `ok`, every result carries a citation in the form `<Document title>, section <N> (<heading>)` (for example `Fee Schedule, section 2 (Transfer fees)`) plus the chunk text and a rounded score; results are ordered by descending score and only those at or above `similarity_threshold` are returned. On `no_relevant_result` the results list is empty and the message is `rag.no_result_message`. The caller must not guess: it says "I do not know" and offers a human handoff. On `invalid_query` the caller asks the customer to rephrase. A query that is empty, whitespace-only, or longer than `max_query_chars` is refused before any embedder or store call.

## Known limitations

- A known limitation is that questions in the bank's domain which the documents do not answer (for example "Can I buy bitcoin with my Rubies account?") can score above the threshold against the General FAQ "About" section, so the threshold cannot separate them. The agent prompt rule plus the evaluation set must cover these.
- The threshold was tuned on 26 plain-English questions and must be re-checked on Pidgin-rewritten queries.
- KYC tier limits come from secondary sources, and the fee bands were not confirmed against the CBN Guide to Charges.
- Top-1 accuracy on the dev set is lower than recall at top_k: recall@top_k is 19/20 while top-1 accuracy is 10/20, because the General FAQ repeats the same figures and often outranks the topic section.

## Sources and currency

Every real rule may be out of date; confirm on the official source. From `rag/facts.yaml` `real_rules`:

| id | URL | Date read | Status |
|---|---|---|---|
| cbn_how_to_lodge_complaints | https://www.cbn.gov.ng/FinInc/FinLit/How_Lodge_Complaints.pdf | 2026-10-27 | verified |
| cbn_consumer_protection_regulations_2_0 | https://www.cbn.gov.ng/Out/2024/CCD/EXPOSURE%20DRAFT%20REVISED%20CONSUMER%20PROTECTION%20REGULATIONS%202.0.pdf | 2026-10-27 | PENDING_USER_CONFIRMATION |
| cbn_tiered_kyc_secondary | https://youverify.co/blog/kyc-onboarding-nigeria-fintechs-cbn-guidelines | 2026-10-27 | PENDING_USER_CONFIRMATION |
| cbn_guide_to_charges | link to be confirmed | 2026-10-27 | PENDING_USER_CONFIRMATION |
| cbn_tiered_kyc_official | https://www.mypryme.com/blog/kyc-tier-limits-nigeria | 2026-10-27 | secondary_source_only |

## Checks

- `scripts/check_rag_step1.sh` — facts sheet and sources register.
- `scripts/check_rag_step2.sh` — policy documents 01, 03, 04.
- `scripts/check_rag_step3.sh` — policy documents 02, 05.
- `scripts/check_rag_step4.sh` — documents 06, 07, 08 and the corpus.
- `scripts/check_rag_step5.sh` — config and the heading chunker.
- `scripts/check_rag_step6.sh` — Titan v2 and mock embedders.
- `scripts/check_rag_step7.sh` — ChromaDB store, ingest and calibration.
- `scripts/check_rag_step8.sh` — search_policy, threshold and dev set.
- `scripts/check_rag_all.sh` — the full acceptance run (files, safety, end-to-end, regression).
