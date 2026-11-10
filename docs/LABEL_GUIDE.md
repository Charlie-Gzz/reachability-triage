# Real-set label guide

How the 50 real-set ground-truth labels are decided in `rt review`. Drafts come from a deterministic
text-search script (`eval/draft_labels.py`, no LLM, independent of the agent); a human confirms or changes each.

## Definitions

- **reachable**: a production path (web request, CLI, background job) can run the vulnerable code in this app,
  and the advisory's preconditions (feature enabled, option set, untrusted input) hold.
- **not_reachable**: the vulnerable code cannot run here: package/function unused, used only in tests or dead
  code, safe API only, or a required precondition is not met (platform, disabled feature, config).
- **uncertain**: cannot be decided without a deep dive into library internals. Excluded from graded metrics,
  so use sparingly. Between R and N with doubt, choose U (a wrong N is the costly error: false suppression).

## Method (framework and transitive findings)

1. Find where the library/framework itself calls the vulnerable function
   (`docker run --rm rt-target-<app> grep -rn <symbol> /opt/venv/lib/python3.*/site-packages/<pkg>`).
2. Find what turns that path on (middleware, decorator, setting, feature).
3. Check whether the app turns it on (`workdirs/<app>`, settings, MIDDLEWARE/INSTALLED_APPS strings).
   Yes → R. No → N. Can't tell → U. Leans R when the framework calls it on every request and the app has that
   component enabled.

## By draft rule

| Draft rule | Draft | What to check |
|---|---|---|
| transitive, never imported (19) | U | Does the parent package use the vulnerable feature in a way this app triggers? urllib3/idna/certifi via `requests`: does the app make outbound HTTP with user-influenced URLs? setuptools: build/install-time only → usually N. mako: Alembic migrations only → usually N. |
| imported, no advisory symbol in first-party code (10) | N | Highest risk of a wrong N: framework-internal calls (request parsing, middleware, template filters, multipart, sessions) never appear by name. Apply the method above. |
| imported, advisory names no function (10) | U | Identify the affected feature from the advisory; grep the app for its use. |
| symbol found in first-party code (8) | R | Production (not tests/scripts/dead code), the library's symbol (not a same-name function), preconditions hold. |
| declared, never imported (3) | N | Also rule out loading by string (INSTALLED_APPS, MIDDLEWARE, backend settings). |

Write a one-line note for every changed label and every judgment call. Don't look at agent verdicts while reviewing.

## Worked example

`healthchecks/django@4.0.1/GHSA-923m-gv2p-w5qp` (`has_vary_header` whitespace): **N, draft confirmed.**
In Django 4.0.1 the only caller is `UpdateCacheMiddleware.process_response` (`django/middleware/cache.py:86`);
healthchecks has no cache middleware in `MIDDLEWARE` (`hc/settings.py:61-73`), no `cache_page`, and no installed
package references either.
