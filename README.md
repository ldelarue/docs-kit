# docs-kit

Auto-generates API documentation from `openapi.json` and CLI reference docs from
[Usage](https://usage.jdx.dev) specs, keeps both honest, and fails the build when docs go stale.

## Install

```bash
uv tool install --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@latest" docs-kit
```

## Quick Start

```bash
docs-kit init      # scaffold docs
docs-kit refresh   # regenerate the reference pages from openapi.json
docs-kit serve     # preview at http://127.0.0.1:8010
```

**Optional**: Wire to mise with `docs-kit init --with-mise`

CI setup: add `DOCS_KIT_PAT` secret (contents: read on ldelarue/docs-kit) and set Pages source to GitHub Actions. The workflow file is only scaffolded when GitHub is detected (GitHub remote or CI env); Stash-hosted repos get the same `mise run docs:check` gate without it.

## CLI

```text
docs-kit init [ROOT] [--spec openapi.json] [--bin NAME] [--no-api] [--no-cli] [--with-mise] [--force] [--docs-kit PATH]
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
`--no-api`/`--no-cli` opt out.

**With mise**: After `docs-kit init --with-mise`, use `mise run docs:*` tasks:

```text
mise run docs:refresh      regenerate everything detected (openapi + cli:spec + pages)
mise run docs:build        build the site
mise run docs:serve        live-reload at http://127.0.0.1:8010
mise run docs:check        CI gate: fails on stale docs
mise run docs:pull-tasks   re-pin .docs-kit/ (shared/mise) to the installed CLI's version
```

`docs:refresh` runs your repo's `openapi` and `cli:spec` tasks only when they
exist, then regenerates pages; `docs:check` fails on any resulting `git diff`.

## CLI reference docs (the standard)

For each binary, `docs-kit init` scaffolds `docs/references/cli-standard.md`: the
contract that keeps CLI docs generated. In short:

- `cli/<bin>.usage.kdl` — committed Usage spec, **generated from your CLI code**
  (Typer via `shared/mise/usage-spec.py`, Go via a hidden `--usage-spec` flag).
- `cli/<bin>.usage.extra.kdl` — hand-written extras spliced into it: `config`
  (env settings), exit codes, `output`/`select` formats, curated examples.
- A `cli:spec` mise task regenerates the contract; the `usage` binary is pinned
  in your mise block (`[tools] usage`) when a CLI is detected; `usage lint` +
  `docs:check` gate every change.

After `uv tool upgrade docs-kit && docs-kit refresh`, also re-pin the task
layer with `docs-kit pull-tasks` so the shared scripts (usage-spec.py,
render-cli-docs) match the CLI version.

## Update

```bash
uv tool upgrade docs-kit && docs-kit refresh
```

## Dev Mode

```bash
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/docs-kit
docs-kit init --docs-kit ~/Dev/docs-kit
```

## License

Documentation and other creative content are licensed under [CC BY 4.0](LICENSE).
