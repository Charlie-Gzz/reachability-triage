# Handoff

Status as of 2026-11-10: **all milestones (M1–M8) done.** The eval is complete, all real-set labels are
human-reviewed, and the README, charts, site and portfolio kit are built from the final numbers.

## The two items the plan asks for

1. **Real-set labels pending review: 0 of 50.** All 50 were reviewed by Charlie (23 drafts confirmed, 27 changed).
   Final split: 5 reachable, 13 not reachable, 32 uncertain. To revisit any label: `uv run rt review`
   (http://127.0.0.1:8765), then `uv run rt refresh`.
2. **Claude calls used: 472 of the 1,500 cap** (`runs/_ledger.jsonl`, one line per call). **Yes, runs stopped on
   the claude.ai session (5-hour) limit**: once on 2026-11-09 (resumed manually) and once on 2026-11-10 at
   about 14:36 (resumed automatically by `scripts/eval_unattended.sh` after the 3pm reset). Nothing was lost,
   because every finding is cached.

## Headline

> Suppresses 58% of scanner noise (19 graded findings) while suppressing 1 of 5 truly reachable ones (real set);
> test-first remediation turned 1 of 9 attempts green with the suite intact.

Benchmark (n=20): full agent 20/20. Details are in `README.md` and `eval/results/results.md`.

## Things to know before showing this to anyone

- **The single remediation "fix" isn't mergeable.** urllib3 1.26.20 → 2.6.0 passed the gate, but `requests==2.27.1`
  pins `urllib3<1.27`. This is disclosed in the README, DECISIONS and the demo script. The gate now runs `uv pip check`
  (`remediate/pipeline.py`, `PIP_CHECK`); the committed result predates that check and was not re-run.
- **Small n.** 5 truly reachable real findings. The README presents counts, not bare rates.
- **Post-hoc benchmark label correction** (`comments-hub`), disclosed in DECISIONS. It favours the agent.

## Your next actions (optional)

- **Make the repo public, then enable Pages:** Settings → Pages → Source: GitHub Actions, then run the `Pages`
  workflow by hand (Actions tab). It publishes `site/`.
- **Record the demo:** `docs/DEMO_SCRIPT.md` (about 2 min, follows the urllib3 case).
- **Slides:** `docs/SLIDES_OUTLINE.md` names the asset for each slide.
- **CV / portfolio:** `docs/PORTFOLIO_CARD.md`.

## Reproduce

```bash
uv sync && uv run rt eval            # every number, no LLM calls
start site\index.html                # case explorer (Windows; `open` on macOS)
bash scripts/eval_unattended.sh      # rerun the whole eval; cached findings are skipped
```

CI (`.github/workflows/ci.yml`) runs ruff and 39 unit tests on every push; it's green.

## Possible next steps

1. Re-run remediation under the new `uv pip check` gate and let it co-upgrade the dependent package (`requests`).
2. Stretch items from the plan: a GIF of a case page for the README, a 7B local model, a transitive-dependency case
   set. Transitive findings are exactly where both the agent and the human labeller were least certain.
3. A second labeller for the real set (inter-rater agreement), and more real findings, to tighten the intervals.
4. Static analysis: resolve framework dispatch (Django middleware, FastAPI dependencies) instead of matching names.
