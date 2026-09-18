# docs-kit

Generate and verify the **Zensical + Diátaxis** documentation site for an API
repository from its `openapi.json`, driven by `mise` tasks in the consuming
repo. Seeded from the `docs-playground` prototype; the CLI-spec machinery from
the prototype is intentionally **not** part of this kit (OpenAPI-only by
design).

## Guarantees

- **Stdlib only, zero subprocesses** in the Python code: the kit is pure file
  I/O. Spec export (`go run` / `uv run`) belongs to the consuming repo's
  `mise` tasks, so the kit never needs a Go or project-Python toolchain.
- **Idempotent and byte-stable**: `refresh` rewrites generated files in whole;
  ordering is sort-stable so `refresh` never rewrites files unchanged and
  semantically-equal specs (e.g. the Go and Python implementations sharing one
  contract) render the same pages regardless of key order.
- **Generated and authored content never mix**: the kit owns
  `docs/references/endpoints.md`, `docs/references/api.md`,
  `docs/reference/swagger.html`, `docs/reference/openapi.json` wholesale; your
  authored markdown is its only other input.

## Commands (run in the target API repo, or pass the repo dir)

| command | effect |
| --- | --- |
| `docs-kit init [--force] [--docs-kit PATH]` | install **or repair** the docs integration: writes missing files, skips byte-identical ones, (re-)adds the `.mise.toml` block and `.gitignore` entries if they were deleted; refuses only if existing files differ from generated content — `--force` overwrites those |
| `docs-kit refresh [--spec openapi.json]` | re-export step is done by the repo (`mise run openapi`), then the kit copies + renders the four generated files |
| `docs-kit check` | renders in memory and byte-compares against the repo; exits non-zero on missing/stale files |

`init` requires `openapi.json` to exist first (it reads `info.title` for the
site title): run the repo's `mise run openapi` before `docs-kit init`.

## Consuming repos

After `docs-kit init`, a repo contains only markdown, `zensical.toml`,
`openapi.json`, the `.mise.toml` block and the CI workflow — no Python project
lifecycle at all. The mise tasks:

```
mise run docs:refresh   # mise run openapi + docs-kit refresh
mise run docs:build     # refresh + zensical build --clean  -> site/
mise run docs:check     # fail if generated docs are stale (CI / git hook)
```

Task bodies prefer a `docs-kit` binary found on `PATH`, else they run the one
from the clone recorded as `$DOCS_KIT` (via `uv run --no-dev --project`), and
the same pattern builds with `zensical` through `uvx`.

## Installation: clone the repo, point tasks at it, update by hand

No PyPI and no version pins — **your local clone is the installed version.**

```bash
# 0. once per machine — clone where you like (this checkout is exactly that):
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/me/docs-kit

# 1. per consumer repo (one command writes everything, incl. $DOCS_KIT):
cd ~/Dev/my-new-api
mise run openapi                                   # produce openapi.json first
uv run --no-dev --project ~/Dev/me/docs-kit docs-kit init
mise run docs:refresh && mise run docs:build

# 2. upgrade the kit manually, whenever you decide — nothing auto-updates:
cd ~/Dev/me/docs-kit && git pull                   # or: git checkout v0.1.1
cd ~/Dev/my-new-api && mise run docs:refresh && git diff docs/
```

`docs-kit init` records its own checkout as `[env] DOCS_KIT = <abs path>`
(override with `--docs-kit`; you may also hand-edit it to a `~/...` path — the
tasks expand it). Because project installs re-validate Python sources by
mtime, `git pull` is picked up on the very next `mise run docs:*` — the
deliberate choice of `uv run --project` over `uvx --from <path>`, which would
cache wheels and silently serve outdated kit code (~70 ms rebuild observed
when changed).

Optional speed/ergonomics: `uv tool install ~/Dev/me/docs-kit` puts `docs-kit`
on `PATH`; the tasks' `command -v` branches start using it automatically (run
`uv tool install` again after each pull, or skip it entirely).

**CI / git hooks:** the scaffolded GitHub workflow gets a commented block to
check out the docs-kit repo (private-repo PAT) and set `DOCS_KIT` to that
checkout, reusing the exact same fallback logic. A git hook just calls
`mise run docs:check`.

The full day-to-day update procedure, CI setup and optional future steps
(kept as reference): [ROADMAP.md](ROADMAP.md).

## Development

```bash
mise install        # python + uv from .mise.toml
mise run test       # uv run pytest
```

Tests (`tests/`) run the commands against the two real API specs and assert:
byte-identical endpoints pages from both (modulo `info.title` prose),
byte-stable double runs, drift detection, and init idempotence guarantees.
The fixtures are copies of `golang-api-playground/openapi.json` and
`python-api-playground/openapi.json` (semantically equal, byte-different).
