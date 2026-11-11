# Slides outline (8 slides)

1. **Problem: scanners are noisy.** 156 findings across three real apps (healthchecks, CTFd, mealie), most of
   them in packages or functions the app never touches. Teams either drown or ignore them.
   *Asset:* `assets/screenshots/overview.png` (hero), or a scanner-output excerpt next to "156".

2. **Approach: reachability, then a proof.** Decide whether the vulnerable code can run in this app, show the
   evidence, then fix with a regression test that goes red → green with the suite intact.
   *Asset:* `assets/diagram/architecture.svg`.

3. **The graph.** Load finding → retrieve advisory (Chroma) → static evidence (AST) → retrieve code → verdict
   (LLM, structured JSON) → self-reflection → route: suppress / flag / remediate.
   *Asset:* `assets/diagram/langgraph.svg`.

4. **Case walkthrough: a clear catch.** `bench/photo-pipeline`: Flask route → job runner → dispatch table →
   `ImageMath.eval`, three hops behind a wrapper.
   *Asset:* `assets/screenshots/case-1.png`.

5. **Case walkthrough: test-first fix, with the honest caveat.** healthchecks urllib3 decompression bomb: a
   generated test fails on 1.26.20 and passes on 2.6.0, with 1,062/1,062 tests passing. But `requests` 2.27 pins
   `urllib3<1.27`, so the gate now runs `uv pip check`.
   *Asset:* `assets/screenshots/case-4.png`, `assets/charts/remediation_funnel.png`.

6. **Results.** Real set (19 graded): 58% noise suppressed, 1 of 5 reachable wrongly suppressed. Benchmark
   (n=20): 20/20 correct. Show the intervals.
   *Asset:* `assets/charts/ablation.png`.

7. **What each part buys.** Without retrieval, recall drops from 100% to 60% and real-set uncertainty reaches 47%.
   Reflection doubles the calls and halves the real-set false suppressions (2 → 1). A local 14B model is 75%
   accurate on the benchmark and twice as slow. Cost: about $0.05–0.08 per finding (API-price estimate).
   *Asset:* `assets/charts/local_vs_claude.png`, `assets/charts/cost_latency.png`.

8. **Lessons.**
   - Labelling is the bottleneck: 32 of 50 real findings stayed `uncertain` even for a human.
   - Retrieval matters more than self-critique.
   - "Tests pass" isn't a sufficient gate; dependency constraints matter too.
   - Freeze the eval before looking, and disclose every post-hoc change.
   *Asset:* `docs/LABEL_GUIDE.md` excerpt, or `assets/screenshots/review.png`.
