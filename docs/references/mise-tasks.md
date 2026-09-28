# mise tasks

The tasks `docs-kit init --with-mise` provides. Names are identical in both
modes; the bodies differ.

## Dependency mode

Written to the committed `mise.toml` by `docs-kit init --with-mise --committed`.

| Task | Runs | Present |
| --- | --- | --- |
| `cli:spec` | `uv run docs-kit spec` | a CLI is detected |
| `docs:refresh` | `uv run docs-kit refresh` | always |
| `docs:build` | `mise run docs:refresh && uv run docs-kit build` | always |
| `docs:serve` | `uv run docs-kit serve` | always |
| `docs:check` | `uv run docs-kit check && git diff --exit-code -- docs openapi.json cli` | always |

The block also pins `[tools] usage = "latest"` when a CLI is detected, in its
own `[tools]` table or in the file's existing one.

## Shim mode

Defined in `.docs-kit/shared/mise/docs.toml`, included from
`mise.local.toml`. Each body runs `docs-kit` from `PATH`, or else
`uv run --no-dev --project "$DOCS_KIT" docs-kit` (a full clone, as on CI).

| Task | Does |
| --- | --- |
| `docs:init` | `docs-kit init --with-mise` |
| `docs:refresh` | runs the repo's `openapi` task, then its `cli:spec` task (each only if defined), then `docs-kit refresh` |
| `docs:build` | `mise run docs:refresh`, then `docs-kit build` |
| `docs:serve` | `docs-kit serve` |
| `docs:check` | like `docs:refresh`'s generator tasks, then `docs-kit check`, then `git diff --exit-code -- docs openapi.json cli` |
| `docs:pull-tasks` | re-pins `.docs-kit/` to the installed CLI's tag; prints `nothing to pull` when `DOCS_KIT` is absolute (checkout mode) |

Bodies are POSIX `sh`.

## Repository tasks docs-kit uses

| Task | Defined by | Called by |
| --- | --- | --- |
| `openapi` | you: writes `openapi.json` | shim `docs:refresh`, `docs:check` |
| `cli:spec` | dependency mode: the block. Otherwise you | shim `docs:refresh`, `docs:check` |

## Exit status

A task fails (non-zero) when its first failing command does. For
`docs:check`, that is `docs-kit check` (stale or missing generated files,
lint errors, stale task block) or `git diff` (regenerated files not
committed).

## Environment

The tasks read the variables documented under
[Configuration](cli/docs-kit.md#configuration): `DOCS_KIT`, `DOCS_KIT_REPO`,
`DOCS_KIT_SKIP_PULL`, `DOCS_PORT`, `FREE_PORT_MIN`, `FREE_PORT_MAX`,
`NO_COLOR`.
