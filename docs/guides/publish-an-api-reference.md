# How to publish an API reference

docs-kit turns an OpenAPI document into two reference pages: an interactive
Swagger UI page and offline endpoint tables. It does not export the spec
itself: producing `openapi.json` stays your application's job.

## Export the spec

Write the spec to `openapi.json` at the repository root, from a task so it
can be re-run. For example, with FastAPI:

```python title="scripts/export_openapi.py"
import json

from myapi.main import app

with open("openapi.json", "w", encoding="utf-8") as f:
    json.dump(app.openapi(), f, indent=2)
    f.write("\n")
```

```toml title="mise.toml"
[tasks.openapi]
description = "Export openapi.json from the FastAPI app"
run = "uv run python scripts/export_openapi.py"
```

Keep the task named `openapi`: in shim mode, `docs:refresh` and `docs:check`
run a task with that name first when it exists.

## Generate the pages

```bash
mise run openapi
mise run docs:refresh
```

```text
  + docs/reference/openapi.json
  + docs/reference/swagger.html
  + docs/references/api.md
  + docs/references/endpoints.md
```

| File | Content |
| --- | --- |
| `docs/reference/openapi.json` | a byte-exact copy of your spec, served with the site |
| `docs/reference/swagger.html` | a standalone Swagger UI page for that copy |
| `docs/references/api.md` | the **API** page, embedding the Swagger UI |
| `docs/references/endpoints.md` | endpoint and schema tables, sorted for stable diffs |

Commit `openapi.json` and the four generated files. `docs-kit check` then
fails whenever the vendored copy or the pages disagree with `openapi.json`.

!!! note "The Swagger page needs network access"

    The Swagger UI bundle loads from the jsDelivr CDN at runtime. The
    endpoint tables work offline.

## Add the pages to the navigation

When `openapi.json` exists at `init` time, the scaffolded `zensical.toml`
already lists them. If you add an API later, add the entry under
`References` yourself:

```toml title="zensical.toml"
{"API" = ["references/api.md", "references/endpoints.md"]},
```

## Use a different spec path

```bash
docs-kit refresh --spec api/openapi.json
docs-kit check --spec api/openapi.json
```

The path is relative to the repository root. An explicit `--spec` that does
not exist is an error; the default `openapi.json` simply switches the API
pipeline off when absent.

## Keep an `openapi.json` out of the docs

```bash
docs-kit refresh --no-api
docs-kit check --no-api
```
