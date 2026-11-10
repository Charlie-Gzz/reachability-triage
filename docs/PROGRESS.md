# Progress

Resume point for the next session. Read this first, then `PLAN.md` (the spec) and `docs/DECISIONS.md` (the why).
Last updated: 2026-11-09 evening (session paused by Charlie).

## Status

| Milestone | State | Notes |
|---|---|---|
| M0 Setup + Phase 0 import | **done** | Phase 0 imported; images built and verified against locks; rescan reproduces all 156 findings exactly; container baselines recorded. Private repo: https://github.com/Charlie-Gzz/reachability-triage |
| M1 RAG layer | **done** | Chroma + FAISS, bge-small. `rt index`, `rt retrieval-check` → `eval/results/retrieval.json` |
| M2 Reachability agent | **done** | LangGraph graph; mock on all 186 findings; Claude on 10 dev + 3 non-eval real findings |
| M3 Test-first remediation | **built, not yet run on Claude** | Plumbing verified on mock (worktree → container → red → upgrade → gate). Needs `full` triage on the real set first. |
| M4 Synthetic benchmark | **done** | 30 cases, 10 dev / 20 test, validated with osv-scanner. One label corrected post hoc (disclosed). |
| M5 Real-set labels + review page | **done, labels pending review** | 50 sampled, drafted (8 reachable / 13 not / 29 uncertain), all `pending_review`. `rt review` works. |
| M6 Evaluation | **partially run** | `full` on bench test: complete (20/20). `full` on real set: 2/50, then stopped on the Claude session limit. Ablations, remediation, local: not run. |
| M7 Case explorer, assets, kit | **built, needs final data** | Site, charts, diagrams, screenshots all generate. Still to write: DEMO_SCRIPT, SLIDES_OUTLINE, PORTFOLIO_CARD; GitHub Pages workflow. |
| M8 README + handoff | **not started** | |

## Current results (partial, regenerate with `rt eval`)

- Benchmark test split, `full` (claude-sonnet-5), n=20: 20/20 correct: false-suppression 0%, precision 100%, recall 100%,
  noise reduction 50% [30–70], 0 uncertain, ~2 calls and ~20 s per finding, ~$0.05 API-price estimate per finding.
  This is after the disclosed `comments-hub` label correction (was 1 false suppression before). n=20 is small and the
  benchmark is probably easy; the real set is the stronger test.
- Retrieval: advisory recall@5 0.98 (n=186), code recall@5 1.00 (n=22); Chroma = FAISS on recall, FAISS faster unfiltered
  (0.1 vs 1.9 ms), Chroma faster with the codebase filter (4.0 vs 9.8 ms).
- Container baselines: healthchecks 1061/1061; CTFd 483 pass + 1 known failure; mealie 853 pass + 1 known failure.

## Claude call budget

82 of 1,500 used (`runs/_ledger.jsonl`, one line per call). The `full` run stopped on the **claude.ai session (5-hour)
limit** at 2026-11-09 19:28 local ("resets 10:20pm America/New_York"). Not a crash; the cache resumes it.
Expected remaining cost: ~48 real × 2.3 + 140 ablation × 2.2 + ~50 remediation ≈ 470 calls. That will likely take
2–3 session windows on Pro, so run it when Claude Code isn't being used for anything else.

## Next steps, in order

1. ~~Decide QUESTIONS #2~~ done: `comments-hub` relabelled (disclosed in DECISIONS).
2. **Eval running unattended** since 2026-11-10 10:18 via `bash scripts/eval_unattended.sh` (log
   `.work/eval_unattended.log`; retries every 30 min on usage limits, then local model, then `rt refresh`).
   If it was killed (e.g. VS Code closed), just rerun the script: everything is cached.
   Order: full real → no-retrieval → no-reflection (bench test + real) → remediation (max 10).
3. **Local model run:** load it with `lms load qwen2.5-coder-14b-instruct` (LM Studio server is on :1235), then
   `uv run rt showcase` (cached stages are skipped; local runs bench test + 20 real findings).
4. Charlie: review the 50 real labels (criteria: `docs/LABEL_GUIDE.md`): `uv run rt review` (keys C/R/N/U, ←/→, J = next pending).
5. `uv run rt refresh` (eval + assets + site), then look at every chart/screenshot again.
6. Write `docs/DEMO_SCRIPT.md`, `docs/SLIDES_OUTLINE.md`, `docs/PORTFOLIO_CARD.md`, `README.md`, `docs/HANDOFF.md`
   (needs final numbers). ~~CI + manual Pages workflow~~ done 2026-11-10 (`.github/workflows/`; Pages not enabled).
7. ~~Unit tests for the new code~~ done 2026-11-10: 39 tests (`test_static`, `test_metrics`, `test_providers`).
8. Polish: ~~case page header shows the config alias~~ done (shows resolved model); featured cases need a
   remediation "full fix" once one exists.

## Commands cheat-sheet

```
uv run rt triage --all --dataset bench --split test --config full   # one stage by hand
uv run rt remediate --config full --max 10
uv run rt eval            # numbers only, no LLM
uv run rt site            # site/ from runs/
uv run rt assets          # charts, diagrams, screenshots
uv run rt review          # label review page (http://127.0.0.1:8765)
```

## Environment notes

- Windows Defender quarantines some GHSA advisory files (exploit strings). The DB build reads advisories from git
  objects instead, and the checked-out advisory files were deleted from `.work/`. Don't re-check them out.
- Avoid shell heredocs for Python edits containing backslash escapes: Git Bash mangled `\b`/`\n` twice this session.
- Docker images: `rt-target-{healthchecks,ctfd,mealie}` (label `project=reachability-triage`), ~3.6 GB total.

## Log

- 2026-11-09: environment checks passed. Docker Desktop 28.2.2 (12 CPU, 16 GB), uv 0.13.7, gh logged in as
  Charlie-Gzz, claude 2.1.275 logged in via claude.ai (Pro), `ANTHROPIC_API_KEY` not set.
- 2026-11-09: Phase 0 imported from `Charlie-Gzz/agentic-vuln-triage@436a48a` (no history). Phase 0 unit tests pass.
- 2026-11-09: advisory DB rebuilt (6,069 GHSA + 7,254 PyPA PyPI records); rescan identical to committed findings
  after fixing a non-deterministic sort of PEP 440-equal fixed versions (certifi `2022.12.7` / `2022.12.07`).
- 2026-11-09: container baselines: healthchecks 25 s, CTFd 122 s, mealie 212 s.
- 2026-11-09: bench committed (a3e1ef4) before prompts; eval config frozen (144cabc).
- 2026-11-09 19:28: `full` stopped on a usage/credit limit after 2 new findings (0 cached). Rerun the same command to resume.
- 2026-11-09: session paused by Charlie; audit, commit.
- 2026-11-09: private GitHub repo created and pushed.
- 2026-11-09: `comments-hub` label corrected with Charlie's approval (see DECISIONS).
- 2026-11-10: unit tests (7 -> 39), CI (ruff + pytest, skips torch/CUDA wheels), manual-only Pages workflow,
  case header shows the resolved model. No Claude eval calls spent; eval still to resume.
- 2026-11-10 11:30: status at ~90% of the session window: `full` done on bench test + real (50), `no-retrieval`
  bench done, real at 23/50; ledger 300 calls. 0/50 labels reviewed yet. Label criteria written to LABEL_GUIDE.md.
- 2026-11-10 11:35: `no-retrieval` stopped on a usage/credit limit after 31 new findings (0 cached). Rerun the same command to resume.
- 2026-11-10 12:05: `no-retrieval` stopped on a usage/credit limit after 0 new findings (31 cached). Rerun the same command to resume.
- 2026-11-10 12:35: `no-retrieval` stopped on a usage/credit limit after 0 new findings (31 cached). Rerun the same command to resume.
- 2026-11-10 13:05: `no-retrieval` stopped on a usage/credit limit after 0 new findings (31 cached). Rerun the same command to resume.
- 2026-11-10 13:36: `no-retrieval` stopped on a usage/credit limit after 0 new findings (31 cached). Rerun the same command to resume.
- 2026-11-10 14:06: `no-retrieval` stopped on a usage/credit limit after 0 new findings (31 cached). Rerun the same command to resume.
- 2026-11-10 14:36: `no-retrieval` stopped on a usage/credit limit after 0 new findings (31 cached). Rerun the same command to resume.
