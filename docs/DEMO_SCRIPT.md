# Demo script (about 2 minutes)

One real finding, followed from scanner alert to a green test: **healthchecks · urllib3 1.26.20 ·
GHSA-2xpw-w6gg-jr37** ("streaming API improperly handles highly compressed data", CVSS 8.9). It is the 4th featured
case on the overview page (`assets/screenshots/case-4.png`).

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:15 | `site/index.html`, hero + tiles | "Scanners flagged 156 vulnerable dependencies across three real Python apps. Most can't be reached from the code. Sieve sorts the real ones from the noise, and tries to fix the real ones with a test that proves it." |
| 0:15–0:30 | Findings table, filter `config=full`, real repos | "Every row is one finding run through the same LangGraph pipeline. Red is reachable, green is suppressed, amber goes to a human." |
| 0:30–0:45 | Open the urllib3 case: step 1 alert, step 2 advisory | "Here's a transitive dependency. healthchecks never imports urllib3 itself. The advisory is retrieved from a Chroma index, and the vulnerable symbols are pulled out by fixed rules: `HTTPResponse.stream`, `read`." |
| 0:45–1:05 | Step 3 static evidence, step 5 verdict | "Static analysis finds no direct call, and says what it searched. The model doesn't stop there: it reasons that `requests` reads response bodies through urllib3, and that healthchecks' webhook transport sends requests to user-configured URLs. So a hostile endpoint can return a decompression bomb. Verdict: reachable, with file and line evidence." |
| 1:05–1:15 | Step 6 reflection | "A second call critiques the verdict before it's accepted." |
| 1:15–1:40 | Remediation panel: generated test, red run | "Now remediation. Claude writes a regression test: a local server returns 5 MiB of gzip that compresses to under 1 KiB, and the test asserts a single read stays bounded. It fails on 1.26.20. Red, for the right reason." |
| 1:40–1:55 | Upgrade diff, suite 1,062/1,062 | "Sieve tries the smallest upgrade, to 2.6.0. The new test goes green, and the whole existing suite still passes in the target's container." |
| 1:55–2:10 | Overview tiles / ablation chart | "Honest caveat: `requests` 2.27 pins urllib3 below 1.27, so this upgrade passes the tests but isn't mergeable. The gate now runs `uv pip check` to catch exactly that. Across the real set, the full agent suppressed 58% of graded findings while wrongly suppressing 1 of 5 reachable ones, and every number comes from committed run records." |

Recording tips: 1440 px wide browser, dark theme, zoom 110%. Pre-open the case page in a second tab. If cutting to
90 seconds, drop the findings-table segment and the reflection step.
