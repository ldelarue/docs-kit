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
| `docs-kit init [--force] [--docs-kit PATH]` | one-time scaffold: `docs/` skeleton, `zensical.toml`, `.github/workflows/docs.yml`, `.gitignore` entries, generated pages, and the `mise` integration block in `.mise.toml` |
| `docs-kit refresh [--spec openapi.json]` | re-export step is done by the repo (`mise run openapi`), then the kit copies + renders the four generated files |
| `docs-kit check` | renders in memory and byte-compares against the repo; exits non-zero on missing/stale files |

`init` requires `openapi.json` to exist first (it reads `info.title` for the
site title): run the repo's `mise run openapi` before `docs-kit init`.

## Consuming repos

After `docs-kit init`, a repo contains only markdown, `zensical.toml`,
`openapi.json`, the `.mise.toml` block and the CI workflow — no Python project
lifecycle. The mise tasks (dispatch with a `uvx` fallback while docs-kit has
no installable source):

```
mise run docs:refresh   # mise run openapi + docs-kit refresh
mise run docs:build     # refresh + zensical build --clean  -> site/
mise run docs:check     # fail if generated docs are stale (CI / git hook)
```

## Installation: private Git, pinned by tag (no PyPI)

docs-kit is **not** a PyPI package and does not need to be. The supported
model is: **mise installs docs-kit from its private git repo, pinned to a
tag** (mise's PyPI backend accepts git sources — see
[ROADMAP.md](ROADMAP.md), Phase 2). Updates are a manual one-line edit, never
`pipx upgrade`-style rolling.

For a new user, the full loop (assuming the repo exists at
`github.com/ldelarue/docs-kit`; run the git auth once with `gh auth setup-git`
or use the `git@github.com:…` SSH form):

```bash
# 1. declare the tool + scaffold a consumer repo in ONE step
cd ~/Dev/my-new-api
mise use 'pypi:git+https://github.com/ldelarue/docs-kit.git@v0.1.1' \
         'pypi:zensical@0.0.62'            # mise writes the [tools] keys; keep them
docs-kit init                              # scaffold docs/ + zensical.toml + tasks
mise run openapi                           # if openapi.json not produced yet: init once more with --force

# 2. daily usage
mise run docs:refresh && mise run docs:build

# 3. upgrade the kit (manual by design): edit the @vX.Y.Z tag in .mise.toml
mise install && mise run docs:refresh && git diff docs/
```

The exact `mise use` key syntax (tag spelling, value shape) should be
validated once in a scratch directory — paste what mise generates rather
than hand-writing it (ROADMAP Phase 2). While the repo has **no remote**, a
local-path bootstrap stands in:

```bash
cd my-api-repo && mise run openapi
uv run --no-dev --project /Users/ladelaru/Dev/me/docs-kit docs-kit init
mise run docs:refresh && mise run docs:build
```

`init` records `[env] DOCS_KIT = <local path>` (overridable: `--docs-kit`) and
writes task bodies that prefer installed binaries and fall back to
`uv run --no-dev --project "$DOCS_KIT" docs-kit` /
`uvx --from "zensical==0.0.62" zensical`. The fallback deliberately uses
`uv run --project`, not `uvx --from <path>`: uv caches wheels built from local
paths and silently serves stale kit code after edits, while a project install
re-validated by source mtime (observed ~70 ms rebuild-when-changed). Local
paths are not a supported mise source — that is precisely what installing
from a git tag fixes; see [ROADMAP.md](ROADMAP.md) for the migration and the
day-to-day update procedure (Phase 3).

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
