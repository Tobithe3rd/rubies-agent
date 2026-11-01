#!/usr/bin/env bash
# Retrieval gates against real Bedrock (query rewriter and embeddings): a minute or two. Run it twice after any
# change to prompts/query_rewrite.md or the rewriter. Keep the Mac awake (caffeinate -i bash ...).
cd "$(dirname "$0")/../.."
python3 scripts/checks/live_retrieval_gates.py "$@"
