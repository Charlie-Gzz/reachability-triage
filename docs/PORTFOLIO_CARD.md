# Portfolio card

**Title:** Sieve: agentic reachability triage for dependency vulnerabilities

**Pitch:** Scanners flag hundreds of vulnerable dependencies, and most can't be reached from your code. Sieve is a
LangGraph agent that decides which ones are real, shows file:line evidence, and tries to fix the real ones with a
regression test that proves it.

**Headline metric:** On 3 real Python apps (19 human-graded findings), Sieve suppressed 58% of scanner noise and
wrongly suppressed 1 of 5 truly reachable vulnerabilities. On a 20-case benchmark built before any prompt existed,
it got 20/20 right.

**Bullets**
- Built a LangGraph pipeline: RAG over 640 advisories (2,039 chunks; Chroma, benchmarked against FAISS) + AST call-path analysis
  → structured Claude verdict → self-reflection. Retrieval alone lifts benchmark recall from 60% to 100%.
- Ran test-first remediation in Docker: the LLM writes a failing regression test, then an upgrade or patch must
  turn it green with the target's full suite intact (1 of 9 succeeded, with a disclosed dependency-pin caveat that
  led to a stricter gate).
- Designed an honest eval: frozen configs, ablations, local-vs-Claude comparison, bootstrap CIs, labels drafted
  independently of the agent and reviewed by hand, and every run record committed and regenerated with no LLM
  calls.

**Tech tags:** Python · LangGraph · Claude (Sonnet via `claude -p`) · Qwen2.5-Coder 14B (LM Studio) · Chroma ·
FAISS · sentence-transformers · Pydantic · Python `ast` · osv-scanner · Docker · pytest · Plotly · matplotlib

**Draft CV bullet:** Built Sieve, an agentic vulnerability-triage tool (LangGraph, Claude, Chroma/FAISS RAG, AST
analysis). It suppressed 58% of scanner noise on three real Python apps while missing 1 of 5 reachable
vulnerabilities, and writes failing regression tests before proposing fixes; evaluated with ablations, a local-model
baseline and bootstrap confidence intervals.
