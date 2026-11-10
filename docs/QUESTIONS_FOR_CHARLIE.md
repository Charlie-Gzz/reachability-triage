# Questions for Charlie

Things the run could not decide alone. Nothing here blocked progress; each item says what was done instead.

1. ~~**GitHub repo not created.** Claude Code's auto-mode safety check blocked `gh repo create ... --private --push`
   (it treats uploading to GitHub as data sharing). The repo is a local git repo with full history. To publish it:
   `gh repo create Charlie-Gzz/reachability-triage --private --source . --push`~~
   **Resolved 2026-11-09:** created (private) and pushed on Charlie's explicit go-ahead.
2. ~~**Benchmark label error: `bench/comments-hub` (lxml GHSA-jq4v-f5q6-mjqq).** Labelled `reachable` when built, but
   the app uses `Cleaner(..., forms=False, safe_attrs_only=True)`, and the advisory requires *both* `forms` and
   `safe_attrs_only` disabled. The agent said `not_reachable`. Checked against real lxml 4.6.2 in a container:
   the app's config strips `formaction` (`<form><button>x</button></form>`); only `safe_attrs_only=False` leaves
   `formaction="javascript:..."` in place. So the agent is right and the label is wrong. It is a test-split case,
   so changing it after seeing results needs your OK. Recommendation: relabel to `not_reachable` / `config_disabled`
   and log it as a disclosed post-hoc correction (it currently counts as the benchmark's only false suppression).~~
   **Resolved 2026-11-09:** Charlie deferred to the recommendation; relabelled and disclosed in DECISIONS.md.
3. **Pending label review:** all 50 real-set labels are machine-drafted (`uv run rt review`). Until reviewed, every
   real-set number is shown as provisional.
