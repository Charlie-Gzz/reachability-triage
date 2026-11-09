# Progress

Resume point for `/autonomous-build`. Newest status at the top of each section.

## Status

| Milestone | State |
|---|---|
| M0 Setup + Phase 0 import | in progress |
| M1 RAG layer | not started |
| M2 Reachability agent | not started |
| M3 Test-first remediation | not started |
| M4 Synthetic benchmark | not started |
| M5 Real-set labels + review page | not started |
| M6 Evaluation | not started |
| M7 Case explorer, assets, kit | not started |
| M8 README + handoff | not started |

## Provider status (M0 step 7)

| Provider | Status |
|---|---|
| mock | ok |
| claude-code | ok: nested `claude -p` works once `CLAUDECODE` is removed from the child env (claude-sonnet-5, ~600 input tokens for a ping) |
| local | LM Studio server found on :1235; Qwen2.5-Coder-14B present but not loaded (loaded on demand for the local run) |

## Claude call budget

Cap 1,500. Used: see `runs/_ledger.jsonl` (one line per call). Running total is updated here after each eval stage.

## Log

- 2026-11-09: environment checks passed. Docker Desktop 28.2.2 (12 CPU, 16 GB), uv 0.13.7, gh logged in as
  Charlie-Gzz, claude 2.1.275 logged in via claude.ai (Pro), `ANTHROPIC_API_KEY` not set.
- 2026-11-09: Phase 0 imported from `Charlie-Gzz/agentic-vuln-triage@436a48a` (no history). 6 unit tests pass.
