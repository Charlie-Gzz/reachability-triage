# Results

_Generated 2026-11-10T03:23:54+00:00 by `rt eval` from `runs/` (no LLM calls)._

**Suppresses 45% of scanner noise with a 9% false-suppression rate (benchmark test split), and fixed 0 real vulnerabilities test-first.**

> Real-set numbers are **provisional**: 50 of 50 real labels are machine-drafted and still pending human review (`rt review`). Ground-truth `uncertain` labels are excluded from graded metrics.

Brackets are 95% bootstrap confidence intervals. With samples this small, differences inside the intervals are noise.

## Synthetic benchmark (test split, final labels)

| Config | Model | n graded | False-suppression | Precision | Recall | Noise reduction | Uncertain | Calls/finding | Tokens in/out | Est. $/finding | p50 s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `full` | claude-sonnet-5 | 20 | 9% [0–29] | 100% [100–100] | 91% [71–100] | 45% [25–65] | 0% | 2 | 6723/2037 | 0.0507 | 19.7 |

## Real-repo eval set (50 findings)

| Config | Model | n graded | False-suppression | Precision | Recall | Noise reduction | Uncertain | Calls/finding | Tokens in/out | Est. $/finding | p50 s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `full` | claude-sonnet-5 | 1 | n/a | n/a | n/a | 100% [100–100] | 0% | 2 | 9034/4092 | 0.0885 | 48.2 |

## Retrieval (Chroma vs FAISS, same embeddings)

| Index | Store | n | R@1 | R@5 | MRR | p50 ms |
|---|---|---|---|---|---|---|
| advisory | chroma | 186 | 0.93 | 0.98 | 0.95 | 1.86 |
| advisory | faiss | 186 | 0.93 | 0.98 | 0.95 | 0.1 |
| code | chroma | 22 | 0.50 | 1.00 | 0.70 | 4.02 |
| code | faiss | 22 | 0.50 | 1.00 | 0.70 | 9.75 |

Claude calls used in total (all runs, incl. development): 82 of the 1,500 cap.
Cost is an API-list-price **estimate**; runs used a Claude subscription via `claude -p`.
