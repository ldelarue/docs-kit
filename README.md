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

## Consuming repos: shared tasks, zero duplication

The `docs:*` **task definitions live only here**, in `shared/mise/docs.toml`.
A consumer repo holds no copies of them — its `.mise.toml` gains just a
pointer (written by `docs-kit init`):

```toml
[vars]
docs_kit = "/Users/you/Dev/me/docs-kit"          # where YOUR clone lives

[env]
DOCS_KIT = "{{ vars.docs_kit }}"

[task_config]
includes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]
```

`mise run docs:refresh|docs:build|docs:check` then behaves identically in
every consumer repo, running in the consumer's root. `docs-kit init` itself is
shared from this file too. Task bodies prefer a `docs-kit` binary on `PATH`,
else run the clone's source through `uv run --no-dev --project "$DOCS_KIT"`
(project installs re-validate sources by mtime, so a `git pull` in the clone
is live on the very next `mise run` — bare `uvx --from <path>` would cache
stale wheels and must not be used).

Because the tasks come from the clone, **you cannot break them by editing a
consumer repo** — and updating `shared/mise/docs.toml` updates all repos at
once, no per-repo sync. A hand-deleted integration block is repaired with the
same `docs-kit init`.

## Installation: clone the repo, point tasks at it, update by hand

No PyPI and no version pins — **your local clone is the installed version.**

```bash
# 0. once per machine — clone where you like (this checkout is exactly that):
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/me/docs-kit

# 1. per consumer repo (one command writes everything, incl. the clone path):
cd ~/Dev/my-new-api
mise run openapi                                   # produce openapi.json first
uv run --no-dev --project ~/Dev/me/docs-kit docs-kit init
mise run docs:refresh && mise run docs:build

# 2. upgrade the kit manually, whenever you decide — nothing auto-updates:
cd ~/Dev/me/docs-kit && git pull                   # or: git checkout v0.1.3
cd ~/Dev/my-new-api && mise run docs:refresh && git diff docs/
```

The clone path is the only machine-specific value in a consumer
`.mise.toml`. Per-machine override — never committed — via
`mise.local.toml` (add it to `.gitignore`):

```toml
[vars]
docs_kit = "/other/machine/docs-kit"
```

`docs-kit init` records its own checkout (`--docs-kit` overrides); the value
must be **absolute** — mise's `includes` templates do not expand `~`.

Optional: `uv tool install ~/Dev/me/docs-kit` puts `docs-kit` on `PATH`; the
tasks' `command -v` branches start using it automatically (re-run it after
each pull, or skip it entirely).

**CI / git hooks:** runners have no personal clone, so the scaffolded
workflow contains a commented recipe: check out `ldelarue/docs-kit` (private
PAT) and write the path into `mise.local.toml` — otherwise the include is
silently skipped and `mise run docs:*` fails with "no task found". A git hook
just calls `mise run docs:check`.

Full day-to-day procedures and optional future steps:
[ROADMAP.md](ROADMAP.md).

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
