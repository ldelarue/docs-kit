# How to document a CLI

A CLI reference page is rendered from a committed **contract**,
`cli/<bin>.usage.kdl`, in the [Usage](https://usage.jdx.dev) format. This
guide covers producing that contract for each kind of CLI and enriching it
with what the code cannot express. The rules the contract follows are in the
[CLI design standard](../references/cli-standard.md).

## Document a Typer CLI

docs-kit detects a Typer CLI when `pyproject.toml` has:

- `typer` in `[project] dependencies`, and
- a console script in `[project.scripts]`.

It then imports the app as `<package>.cli:app`, or `<module>:app` when the
script already points at a `.cli` module:

```toml title="pyproject.toml"
[project.scripts]
mycli = "mycli.cli:app"   # imported as mycli.cli:app
```

1. Give every argument, option and command a help string: they render
   verbatim.

    ```python
    @app.command()
    def sync(
        dry_run: bool = typer.Option(False, help="print the plan, change nothing"),
    ) -> None:
        """synchronise the local cache"""
    ```

2. Regenerate the contract and the page:

    ```bash
    mise run docs:refresh     # or: mise run cli:spec, then docs:refresh
    ```

3. Commit the code, `cli/mycli.usage.kdl` and `docs/references/cli/mycli.md`
   together.

!!! note "Where the import happens"

    `docs-kit spec` imports your app in the venv docs-kit runs from. That
    is why Python repositories install docs-kit as a
    [dev dependency](install.md#install-as-a-dev-dependency): a uv-tool
    install cannot import your package, and prints
    `note: mycli: cannot import mycli.cli:app here` instead.

## Add exit codes, settings and examples

Create `cli/<bin>.usage.extra.kdl`, by hand. Its nodes are spliced into the
generated contract on every `cli:spec` run:

```kdl title="cli/mycli.usage.extra.kdl"
// settings read from the environment, rendered as a Configuration section
config {
  prop "jobs" type="int" default=4 help="Parallel workers." { env "MYCLI_JOBS" }
}

// exit codes for the whole CLI
exit_code 0 "success"
exit_code 1 "sync failed; see stderr"

// curated examples, rendered near the top of the page
example """
mycli sync --dry-run
MYCLI_JOBS=8 mycli sync
"""

// nodes inside `cmd <name>` land in that command's section
cmd sync {
    exit_code 3 "cache locked by another process"
}
```

Then run `mise run docs:refresh`.

The merge refuses to guess. It fails when:

- a `cmd` path in the extra no longer exists in the code (renamed or removed
  command),
- both the code and the extra declare a root `config` block,
- a `cmd` block puts its body on the same line (`cmd sync { … }`): open the
  brace, then one node per line.

`usage lint` runs on every refresh; a lint error fails the pipeline.

## Document a Go / cobra CLI

docs-kit detects a Go CLI when `go.mod` requires `github.com/spf13/cobra`,
and names it after the module's last path segment.

1. Add a hidden `--usage-spec` flag to your root command that prints the
   command tree as a Usage spec (Usage provides cobra integration; see
   [usage.jdx.dev](https://usage.jdx.dev)).

2. Pipe it into docs-kit from a `cli:spec` task in your committed
   `mise.toml`:

    ```toml title="mise.toml"
    [tasks."cli:spec"]
    description = "Regenerate cli/mycli.usage.kdl from cobra"
    run = "go run . --usage-spec | docs-kit spec --bin mycli"
    ```

3. `mise run docs:refresh`. In shim mode, `docs:refresh` and `docs:check`
   run your `cli:spec` task first.

The extra file works exactly as for Typer.

## Document any other CLI

Write `cli/<bin>.usage.kdl` by hand, lint it, and render it:

```bash
usage lint cli/mycli.usage.kdl
mise run docs:refresh
```

A committed contract with no generator behind it is the source of truth, so
`docs-kit spec` leaves it alone.

## Name a CLI explicitly

When autodetection misses a binary, name it:

```bash
docs-kit init --bin mycli
docs-kit refresh --bin mycli
```

`--bin` is repeatable. `--no-cli` turns the CLI pipeline off entirely.

## Add a second CLI to an existing site

Contracts and pages are generated per binary, but `zensical.toml` belongs to
you after `init`. Add the new page to the `CLI` nav entry yourself:

```toml title="zensical.toml"
{"CLI" = ["references/cli/mycli.md", "references/cli/myctl.md", "references/cli-standard.md"]},
```

## Generate man pages and completions

The same contract feeds the `usage` binary:

```bash
usage generate manpage -f cli/mycli.usage.kdl
usage generate completion zsh -f cli/mycli.usage.kdl
```
