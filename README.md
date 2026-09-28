# docs-kit

Auto-generates API documentation from `openapi.json` and CLI reference docs from
[Usage](https://usage.jdx.dev) specs, keeps both honest, and fails the build when docs go stale.

## Quick Start (Python CLIs: docs-kit as a dev dependency)

```bash
uv add --dev "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@v0.5.0"   # once, committed
uv run docs-kit init --with-mise --committed   # scaffold + committed mise.toml task block
mise install && uv sync                        # everything arrives: kit, exporter, usage tool
mise run docs:refresh && mise run docs:serve
```

No clone of docs-kit, no `$DOCS_KIT`, no gitignored `mise.local.toml` docs
wiring: the committed `mise.toml` block pins `[tools] usage` and the five
one-liner tasks (`cli:spec`, `docs:refresh`, `docs:build`, `docs:serve`,
`docs:check`), all calling `uv run docs-kit …`. `mise.local.toml` keeps only
secrets and personal overrides. `docs-kit check` (inside `docs:check`) drift-
gates the block itself: after a kit upgrade, re-run `docs-kit init --with-mise
--committed` to refresh it.

**No Python venv? (Go CLIs, kit development)** - the shim mode below. One-off
CLI installs also work as a tool: `uv tool install --from "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@latest" docs-kit`.

## Quick Start (shim mode: no-virtualenv / Go consumers)

```bash
docs-kit init --with-mise   # pulls .docs-kit/shared/mise, wires mise.local.toml
mise run docs:refresh       # same engine: docs.toml drives docs-kit + shared scripts
docs-kit serve
```

CI setup: on your repo, set Pages source to GitHub Actions - nothing else. The generated `docs.yml` clones this public kit with the default `GITHUB_TOKEN` (no secrets, so fork PRs work too). The workflow file is only scaffolded when GitHub is detected (GitHub remote or CI env); Stash-hosted repos get the same `mise run docs:check` gate without it.

## CLI

```text
docs-kit init [ROOT] [--spec openapi.json] [--bin NAME] [--no-api] [--no-cli] [--with-mise] [--committed] [--force] [--docs-kit PATH]
docs-kit spec [ROOT] [--bin NAME] [--extra FILE] [--out FILE] [--no-cli]
docs-kit render [ROOT]
docs-kit refresh [ROOT] [--spec openapi.json] [--bin NAME] [--no-api] [--no-cli]
docs-kit check [ROOT] [--spec openapi.json] [--bin NAME] [--no-api] [--no-cli]
docs-kit serve [ROOT] [--port N] [--host H]
docs-kit pull-tasks [ROOT]
docs-kit --version
```

Pipelines are **autodetected** per command: the API pipeline runs when
`openapi.json` (or `--spec`) is present, the CLI pipeline when `cli/*.usage.kdl`,
a Typer console-script, or `spf13/cobra` in `go.mod` is. Both when both; neither
refuses with an actionable message. `--bin NAME` names a CLI explicitly,
`--no-api`/`--no-cli` opt out. `spec` regenerates the `cli/*.usage.kdl`
contracts (Typer apps are introspected in THIS venv - dependency mode puts
docs-kit in the consumer's venv, so `uv run docs-kit spec` sees the repo's own
app; cobra cores are piped: `go run . --usage-spec | docs-kit spec`), `render`
writes `docs/references/cli/<bin>.md` with the `usage` binary, and `refresh`
chains both.

**With mise**: shim consumers wire `docs.toml` via `--with-mise`; dependency-mode
repos get the block from `--with-mise --committed`. Either way:

```text
mise run cli:spec          regenerate cli/*.usage.kdl from the code
mise run docs:refresh      regenerate everything detected (contracts + pages)
mise run docs:build        build the site
mise run docs:serve        live-reload at http://127.0.0.1:8010
mise run docs:check        CI gate: fails on stale docs (and on glue drift)
```

`docs:refresh` runs your repo's `openapi` and `cli:spec` tasks only when they
exist, then regenerates pages; `docs:check` fails on any resulting `git diff`.

To fail drift at commit time too, wire `mise run docs:check` into your own
git-hook runner: in [hk](https://hk.jdx.dev), a `pre-commit`-only step
path-gated to your docs sources does it (the worked recipe is this repo's
`hk.pkl` `docs-drift` step). Hooks are per-clone opt-in; the CI `check`
job stays the non-bypassable gate.

## CLI reference docs (the standard)

For each binary, `docs-kit init` scaffolds `docs/references/cli-standard.md`: the
contract that keeps CLI docs generated. In short:

- `cli/<bin>.usage.kdl` — committed Usage spec, **generated from your CLI code**
  (`uv run docs-kit spec`: Typer apps are introspected with the bundled
  exporter, Go cores are piped through a hidden `--usage-spec` flag).
- `cli/<bin>.usage.extra.kdl` — hand-written extras spliced into it: `config`
  (env settings), exit codes, `output`/`select` formats, curated examples.
- A `cli:spec` mise task regenerates the contract; the `usage` binary is pinned
  (`[tools] usage`) in the same committed `mise.toml`; `usage lint` +
  `docs:check` gate every change.

After `uv tool upgrade docs-kit && docs-kit refresh` (tool installs), also
re-pin the task layer with `docs-kit pull-tasks` so the shim payload scripts
(usage-spec.py, render-cli-docs) match the CLI version. Dependency-mode repos
have no layer to re-pin: bump the dev-dep tag, then re-run `docs-kit init
--with-mise --committed` when `docs-kit check` reports glue drift.

## Update

Dependency mode: `uv lock --upgrade-package docs-kit && uv sync` (explicit
by design - the git pin never moves on its own). Tool installs:

```bash
uv tool upgrade docs-kit && docs-kit refresh
```

## Kit development

```bash
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/docs-kit
docs-kit init --docs-kit ~/Dev/docs-kit
```

## License

Documentation and other creative content are licensed under [CC BY 4.0](LICENSE).
