# Third-party targets

The evaluation runs against three public, permissively licensed (or AGPL) Python web apps. They are cloned at pinned
commits into `workdirs/` (gitignored) and used as **read-only references**: no target source files are committed here,
and nothing is pushed upstream. Run records and the case explorer include only short excerpts (evidence lines, generated
tests, and patch diffs), each with its file path and a link to the upstream project at the pinned commit.

| Target | Version | License | Upstream | Pinned commit |
|---|---|---|---|---|
| healthchecks | v1.25.0 | BSD-3-Clause | https://github.com/healthchecks/healthchecks | 731c54529c94a795454745f0fec244669dd2be1e |
| CTFd | 3.4.0 | Apache-2.0 | https://github.com/CTFd/CTFd | 7d56e59e1afcfbe919ce4050e458dfd6cba3fa00 |
| mealie | v1.0.0 | AGPL-3.0 | https://github.com/mealie-recipes/mealie | f0bbe796ce40ef32a4a00eecdfb0efe4eef9da07 |

Advisory data: GitHub Advisory Database (CC-BY-4.0) and PyPA Advisory Database (CC-BY-4.0), at the commits in
`targets.yaml`. The synthetic benchmark apps in `bench/cases/` were written for this project.
