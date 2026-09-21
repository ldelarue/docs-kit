# docs-kit

Auto-generates API documentation from `openapi.json`, keeps it honest, and fails the build when docs go stale.

## Install

```bash
uv tool install --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@latest" docs-kit
```

## Quick Start

```bash
docs-kit init                    # scaffold docs
docs-kit build                   # generate & build the site
docs-kit serve                   # view at http://127.0.0.1:8010
```

**Optional**: Wire to mise with `docs-kit init --with-mise`

CI setup: add `DOCS_KIT_PAT` secret (contents: read on ldelarue/docs-kit) and set Pages source to GitHub Actions.

## CLI

```text
docs-kit init [ROOT] [--spec openapi.json] [--with-mise] [--force]
docs-kit build [ROOT] [--spec openapi.json]
docs-kit check [ROOT] [--spec openapi.json]
docs-kit serve [ROOT] [--port N]
```

**With mise**: After `docs-kit init --with-mise`, use `mise run docs:*` tasks:

```text
mise run docs:refresh      regenerate from openapi.json
mise run docs:build        build the site
mise run docs:serve        live-reload at http://127.0.0.1:8010
mise run docs:check        CI gate: fails on stale docs
mise run docs:pull-tasks   re-pin .docs-kit/ (shared/mise) to the installed CLI's version
```

## Update

```bash
uv tool upgrade docs-kit && mise run docs:refresh
```

## Dev Mode

```bash
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/docs-kit
docs-kit init --docs-kit ~/Dev/docs-kit
```

## License

Documentation and other creative content are licensed under [CC BY 4.0](LICENSE).
