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

Bootstrap a new repo:

```bash
cd my-api-repo && mise run openapi                     # produce openapi.json
uv run --no-dev --project /Users/ladelaru/Dev/me/docs-kit docs-kit init
mise run docs:refresh && mise run docs:build
```

## Installation model (mise tool, pinned by git tag)

Target state: the consuming `.mise.toml` declares `docs-kit` and `zensical`
as mise PyPI-backend tools installed from a pinned git ref, so the binaries sit
on `mise`'s PATH and task calls are plain and instant:

```toml
[tools]
"pypi:ldelarue/docs-kit" = "0.1.0"    # exact key confirmed via `mise use`
"pypi:zensical" = "0.0.62"
```

docs-kit has **no git remote yet**, and the mise pypi backend supports neither
local paths nor `git+file` URLs, so until this repo is pushed the generated
`.mise.toml` block instead:

- records `[env] DOCS_KIT = <local path>` (overridable: `--docs-kit`),
- writes task bodies that prefer the installed binaries and fall back to
  `uv run --no-dev --project "$DOCS_KIT" docs-kit` /
  `uvx --from "zensical==0.0.62" zensical`. The fallback deliberately uses
  `uv run --project`, not `uvx --from <path>`: uv caches wheels built from
  local paths per-content and silently serves stale kit code after edits,
  while a project install re-validates by source mtime (observed ~70 ms
  rebuild-when-changed, ~200-500 ms call overhead).
- keeps the final `pypi:` pins as comments.

To finish the migration once remote + tag exist:

```bash
cd my-api-repo
mise use 'pypi:ldelarue/docs-kit@0.1.0'   # paste the key mise generates
mise use 'pypi:zensical@0.0.62'
# uncomment the pins in the docs block; optionally simplify the task bodies
```

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
