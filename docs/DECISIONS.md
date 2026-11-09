# Decisions

Each entry: what was decided, why, and what it affects. Newest at the bottom of each section.

## Carried over from Phase 0 (agentic-vuln-triage)

- **Scan what's installed, not what's declared.** Each target's venv is built with production deps only,
  frozen to `locks/<target>.runtime.txt`, and that file is scanned. Scanning `requirements.txt` misses
  transitive deps (healthchecks declares 11 packages, installs 25); scanning the full lock includes dev
  tools like mkdocs that never run in production. Dev-only findings are excluded by rule, not by an LLM.
- **Pinned advisory DB.** OSV data changes daily. `rt db` builds osv-scanner's offline DB from the GitHub
  Advisory Database + PyPA Advisory Database at the commits in `targets.yaml`, so a rescan reproduces the
  committed findings exactly.
- **One finding = one (target, package, version, vulnerability).** osv-scanner groups aliases
  (GHSA / PYSEC / CVE for the same bug); each group is one finding and one label.
- **Test baselines recorded up front.** The remediation gate is "new test red to green, existing suite
  unchanged", which needs a known starting point per target.
- **Targets:** healthchecks v1.25.0 (Django), CTFd 3.4.0 (Flask), mealie v1.0.0 (FastAPI). Rejected:
  flaskbb, netbox, redash, privacyidea, paperless-ngx, wagtail bakerydemo (unpinned deps or suites that
  need Postgres/Redis/OCR).

## This repo

- **2026-11-09 · `/autonomous-build` skill not installed in this session.** The plan defers general
  working rules to that skill; it wasn't available, so the run followed the rules the plan names
  (no mid-run questions, DECISIONS.md, PROGRESS.md, honest results, handoff) directly.
- **Product name: Sieve.** It does one thing: lets real, reachable vulnerabilities through and holds
  back the noise. Short, verb-like, works as a logo (a violet funnel mesh).
- **Phase 0 history not copied.** Files imported from `Charlie-Gzz/agentic-vuln-triage@436a48a`.
- **Phase 0 modules moved into `src/reachability_triage/scan/`** to match the target layout
  (`scan.py` → `scan/osv.py`). Behaviour unchanged.
- **Targets live in `workdirs/<name>`** (gitignored) instead of `.work/targets/`, per the plan layout.
- **Git line endings forced off for target checkouts** (`core.autocrlf=false`): Charlie's global Git has
  `autocrlf=true`, which would turn target files CRLF before they're copied into Linux containers.
- **Target images are built from the committed `locks/<t>.test-env.txt` with `--no-deps`**, not by
  re-running the install recipes. The freeze is complete, so this reproduces the Phase 0 environment
  exactly and avoids re-resolving on a different OS. `rt verify-lock` diffs each image against the lock.
- **Containers copy the worktree in** (mounted read-only at `/src`, copied to `/app`) instead of running
  on the Windows bind mount: native filesystem speed for test suites, and every run starts clean.
- **`claude-code` provider = `claude -p` subprocess** (not the Python Agent SDK): one fewer dependency, and
  the CLI flags map 1:1 to the plan's rules. Flags (checked against code.claude.com/docs headless + CLI
  reference, and `claude --help` for v2.1.275): `--tools ""` (no tools), `--max-turns 1`,
  `--system-prompt` (replaces Claude Code's own prompt), `--safe-mode` (no CLAUDE.md, skills, plugins,
  hooks, MCP, auto-memory, but keeps OAuth login), `--strict-mcp-config`, `--setting-sources ""`,
  `--disable-slash-commands`, `--no-session-persistence`, `--output-format json`. Runs from a fresh temp
  dir with `CLAUDECODE` removed from the child env. A test call used ~600 input tokens, i.e. nothing
  from this repo leaked in. Never `--bare` (needs an API key).
- **Claude model: `sonnet` alias** (resolved to claude-sonnet-5 at test time). Charlie is on a Pro plan;
  Sonnet gives good reasoning per unit of plan usage, and Opus would burn the window several times faster.
- **Local endpoint discovered at `http://localhost:1235`** (LM Studio, found via `lms status`; none of
  1234/11434/8080/1337 answered). The model is loaded only for the local run, to keep RAM free for
  Docker on a 16 GB machine.
