# How to configure mise and uv for docs-kit

`docs-kit init --with-mise` gives your repository the `docs:*` tasks. Where
those tasks come from depends on how docs-kit is installed; pick the section
that matches your repository.

| Section | For | Tasks live in | Committed? |
| --- | --- | --- | --- |
| [Dependency mode](#python-repository-dependency-mode) | Python / uv projects | a marked block in `mise.toml` | yes |
| [Shim mode](#go-or-no-venv-repository-shim-mode) | Go, or no Python venv | `.docs-kit/`, included from `mise.local.toml` | no (per clone) |
| [Checkout mode](#kit-development-checkout-mode) | working on docs-kit itself | your docs-kit clone | no |

## Python repository: dependency mode

1. Add docs-kit to the dev dependencies and scaffold with `--committed`:

    ```bash
    uv add --dev "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@vX.Y.Z"
    uv run docs-kit init --with-mise --committed
    ```

2. Install what the new block pins, and sync the venv:

    ```bash
    mise trust && mise install && uv sync
    ```

3. Commit `pyproject.toml`, `uv.lock`, `mise.toml`, `.gitignore`,
   `zensical.toml` and `docs/`.

Anyone who clones the repository now only needs `mise install && uv sync`.

### What lands in `mise.toml`

init writes one block between two marker comments (most descriptions
trimmed here):

```toml title="mise.toml"
# --- docs-kit tasks vX.Y.Z ---
[tools]
usage = "latest" # (1)!

[tasks."cli:spec"] # (2)!
description = "Regenerate cli/*.usage.kdl contracts from the code (docs-kit spec)"
run = "uv run docs-kit spec"

[tasks."docs:refresh"]
run = "uv run docs-kit refresh"

[tasks."docs:build"]
run = "mise run docs:refresh && uv run docs-kit build"

[tasks."docs:serve"]
run = "uv run docs-kit serve"

[tasks."docs:check"]
run = "uv run docs-kit check && git diff --exit-code -- docs openapi.json cli"
# --- end docs-kit tasks ---
```

1.  Only when a CLI is detected. If your file already has a `[tools]`
    table, the `usage` line is added to **that** table instead: a second
    `[tools]` header would be invalid TOML, and mise would skip the file.
2.  `cli:spec` and `[tools]` are omitted when the repository has no CLI.

Keep your own tools and tasks **outside** the markers. The block itself is
drift-checked: after hand edits, or after upgrading docs-kit, `docs-kit
check` reports

```text
stale:   mise.toml docs-kit task block (v<old> vs expected v<installed> + canonical body)
```

and re-running `uv run docs-kit init --with-mise --committed` rewrites it
(idempotently; it moves to the end of the file).

!!! note "`mise.toml` or `.mise.toml`"

    init writes into the file that already carries the block, else your
    existing `mise.toml` or `.mise.toml`, else a new `mise.toml`. If the
    merged file would not parse as TOML, nothing is written and the block is
    printed for you to paste.

`mise.local.toml` is git-ignored in this mode and stays yours: use it for
secrets and [personal overrides](#tune-the-tasks-with-environment-variables).

## Go or no-venv repository: shim mode

1. Install docs-kit as a [uv tool](install.md#install-as-a-uv-tool), then:

    ```bash
    docs-kit init --with-mise
    ```

2. init fetches the task layer into `.docs-kit/` (a sparse checkout of
   `shared/mise/` at the tag matching your CLI version) and creates
   `mise.local.toml`:

    ```toml title="mise.local.toml"
    [vars]
    docs_kit = ".docs-kit"

    [env]
    DOCS_KIT = "{{ vars.docs_kit }}"

    [task_config]
    includes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]

    [tools]
    usage = "latest"
    ```

    Both `.docs-kit/` and `mise.local.toml` are added to `.gitignore`.

3. Install `usage` and list the tasks:

    ```bash
    mise install
    mise tasks
    ```

    You get `docs:init`, `docs:refresh`, `docs:build`, `docs:serve`,
    `docs:check` and `docs:pull-tasks`.

Because both files are git-ignored, **every clone runs
`docs-kit init --with-mise` once** (or `mise run docs:init` once the layer
exists). CI recreates them itself.

### Hook your own generators in

In shim mode, `docs:refresh` and `docs:check` first run your repository's
`openapi` and `cli:spec` tasks **when they exist**. Define them in your
committed `mise.toml`:

```toml title="mise.toml"
[tasks."cli:spec"]
description = "Regenerate cli/mycli.usage.kdl from cobra"
run = "go run . --usage-spec | docs-kit spec --bin mycli"

[tasks.openapi]
description = "Export openapi.json"
run = "go run ./cmd/api -spec > openapi.json"
```

### Your `mise.local.toml` already exists

init appends the keys when the result is still valid TOML. If your file
already has its own `[vars]`, `[env]` or `[task_config]` tables, init prints
the block instead: **merge** the three keys into your existing tables, and
keep one header of each.

```toml title="mise.local.toml (merged)" hl_lines="3 7 10"
[vars]
my_var = "..."
docs_kit = ".docs-kit"

[env]
MY_TOKEN = "..."
DOCS_KIT = "{{ vars.docs_kit }}"

[task_config]
includes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]
```

init never edits `.mise.toml` or `mise.toml` in this mode.

## Kit development: checkout mode

Point init at a docs-kit clone with an **absolute** path:

```bash
docs-kit init --with-mise --docs-kit ~/Dev/docs-kit
```

Nothing is fetched: `vars.docs_kit` records the clone path and the tasks
run the `shared/mise/docs.toml` of your working tree, so edits to the task
bodies apply immediately. To go back to the pinned layer, set
`docs_kit = ".docs-kit"` in `mise.local.toml` and run `docs-kit pull-tasks`.

## Tune the tasks with environment variables

Set these in the `[env]` table of `mise.local.toml` (in shim mode, the one
that already holds `DOCS_KIT`):

```toml title="mise.local.toml"
[env]
DOCS_PORT = "8123"        # always serve on this exact port
FREE_PORT_MIN = "8100"    # or: lease the first free port in 8100-8199
FREE_PORT_MAX = "8199"
DOCS_KIT_REPO = "https://github.com/ldelarue/docs-kit.git"  # pull the layer over HTTPS
NO_COLOR = "1"
```

The full list, with defaults, is in the
[CLI reference](../references/cli/docs-kit.md#configuration).

## Check the result

```bash
mise tasks | grep -E '^(docs:|cli:spec)'
mise run docs:check
```

If a `docs:*` task is missing in shim mode, the layer did not sync: run
`docs-kit pull-tasks`.
