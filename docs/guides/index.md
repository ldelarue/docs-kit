# Guides

How-to guides are recipes for a job you already have in mind. They assume
you know the basics; if you don't yet, start with the
[tutorial](../tutorials/first-docs-site.md).

## Set up

- **[Install docs-kit](install.md)**: as a dev dependency, a uv tool, or from
  a local checkout.
- **[Configure mise and uv](configure-mise-and-uv.md)**: dependency, shim and
  checkout modes, existing configs, environment overrides.
- **[Upgrade docs-kit](upgrade.md)**: move the CLI, the tasks and the
  stamped files together.

## Write and preview

- **[Preview the docs locally](preview.md)**: live reload, fixed ports,
  side-by-side previews, branch previews, the static build.
- **[Document a CLI](document-a-cli.md)**: Typer, cobra or hand-written
  contracts, plus exit codes, settings and examples.
- **[Publish an API reference](publish-an-api-reference.md)**: from
  `openapi.json` to Swagger UI and endpoint tables.

## Ship

- **[Fail the build on stale docs](gate-drift.md)**: GitHub Pages, other CI,
  pre-commit hooks, and reading a failure.
