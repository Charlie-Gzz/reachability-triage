# Results

_Generated 2026-11-10T23:14:41+00:00 by `rt eval` from `runs/` (no LLM calls)._

**Suppresses 58% of scanner noise (19 graded findings) while suppressing 1 of 5 truly reachable ones (real set); test-first remediation turned 1 of 9 attempts green with the suite intact.**

Brackets are 95% bootstrap confidence intervals. With samples this small, differences inside the intervals are noise.

## Synthetic benchmark (test split, final labels)

| Config | Model | n graded | False-suppression | Precision | Recall | Noise reduction | Uncertain | Calls/finding | Tokens in/out | Est. $/finding | p50 s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `full` | claude-sonnet-5 | 20 | 0% [0–0] | 100% [100–100] | 100% [100–100] | 50% [30–70] | 0% | 2 | 6723/2037 | 0.0507 | 19.7 |
| `no-retrieval` | claude-sonnet-5 | 20 | 20% [0–50] | 86% [50–100] | 60% [29–89] | 40% [20–60] | 15% | 2.2 | 4471/2434 | 0.0499 | 31.0 |
| `no-reflection` | claude-sonnet-5 | 20 | 0% [0–0] | 91% [71–100] | 100% [100–100] | 45% [25–65] | 0% | 1 | 3377/882 | 0.0234 | 9.3 |
| `local` | qwen2.5-coder-14b-instruct | 20 | 20% [0–50] | 73% [44–100] | 80% [50–100] | 35% [15–55] | 0% | 2.1 | 3674/350 | 0.0 | 43.4 |

## Real-repo eval set (50 findings)

| Config | Model | n graded | False-suppression | Precision | Recall | Noise reduction | Uncertain | Calls/finding | Tokens in/out | Est. $/finding | p50 s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `full` | claude-sonnet-5 | 19 | 20% [0–67] | 50% [0–100] | 40% [0–100] | 58% [37–79] | 16% | 2.28 | 9968/3603 | 0.0839 | 35.7 |
| `no-retrieval` | claude-sonnet-5 | 19 | 0% [0–0] | 0% [0–0] | 0% [0–0] | 47% [26–68] | 47% | 2.88 | 6420/4199 | 0.0822 | 50.4 |
| `no-reflection` | claude-sonnet-5 | 19 | 40% [0–100] | 50% [0–100] | 40% [0–100] | 63% [42–84] | 5% | 1 | 4288/1295 | 0.0323 | 13.5 |
| `local` | qwen2.5-coder-14b-instruct | 6 | 100% [100–100] | n/a | 0% [0–0] | 67% [33–100] | 0% | 2.6 | 6125/503 | 0.0 | 76.8 |

## Test-first remediation

9 reachable findings attempted → 3 with a failing (red) test → **1 fixed green with the suite intact** ({'upgrade': 1}). Failure reasons: {'patch_failed': 2, 'no_failing_test': 6}.

## Retrieval (Chroma vs FAISS, same embeddings)

| Index | Store | n | R@1 | R@5 | MRR | p50 ms |
|---|---|---|---|---|---|---|
| advisory | chroma | 186 | 0.93 | 0.98 | 0.95 | 1.86 |
| advisory | faiss | 186 | 0.93 | 0.98 | 0.95 | 0.1 |
| code | chroma | 22 | 0.50 | 1.00 | 0.70 | 4.02 |
| code | faiss | 22 | 0.50 | 1.00 | 0.70 | 9.75 |

Claude calls used in total (all runs, incl. development): 472 of the 1,500 cap.
Cost is an API-list-price **estimate**; runs used a Claude subscription via `claude -p`.
