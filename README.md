# docs-kit

Scaffold, regenerate, and CI-verify a **Zensical + Diátaxis** docs site for an API repository from its `openapi.json`, with a `docs:*` mise task layer version-locked to the CLI.

## Install (private repo: needs an SSH key, or `gh auth setup-git`)

```bash
uv tool install --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@latest" docs-kit
uv tool install --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@vX.Y.Z" docs-kit   # pinned
uv add "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@latest"                            # uv-project dependency
```

## Setup in a repository

```bash
mise run openapi                       # your repo's own spec-export task: produce openapi.json first
docs-kit init                          # scaffolds docs; .mise.toml is NOT touched; prints the paste block below
# (add --without-mise to scaffold docs only: no .docs-kit/ layer, no task wiring)
# copy-paste this into mise.local.toml (mise auto-loads it); if you already have these
# tables, merge the keys - one of each header only, a duplicate is invalid TOML:
[vars]
docs_kit = ".docs-kit"

[env]
DOCS_KIT = "{{ vars.docs_kit }}"

[task_config]
includes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]
mise run docs:refresh && mise run docs:build   # then commit; docs:* tasks are live
```

`docs-kit init` prints exactly that block (the values are the ones it recorded); re-running init
detects the pasted keys and only re-prints the block when its content went stale (older kit
version or hand edits). `.docs-kit/` holds only the pinned `shared/mise/` task layer that init
pulls (tag `v$(docs-kit --version)`); the pull is best-effort - until a matching tag exists it
leaves `.docs-kit/` empty with a warning, so run init from a dev checkout (`--docs-kit`) meanwhile.

## Tasks (`mise run docs:*`)

```text
docs:init         docs-kit init (re-run to re-print the current block and re-pin the layer)
docs:refresh      mise run openapi, then docs-kit refresh (regenerate the 4 owned files)
docs:build        refresh, then zensical build --clean -> site/
docs:serve        live-reload on http://127.0.0.1:8010, or the next free 8000-8999 port if taken
                  (pin exactly with DOCS_PORT=...)
docs:check        CI gate: fails on stale docs or an uncommitted diff
docs:pull-tasks   re-pin .docs-kit/ (shared/mise) to the installed CLI's version
```

## Update

```bash
uv tool upgrade docs-kit && mise run docs:pull-tasks && mise run docs:check
```

## Dev checkout (dogfood templates/tasks; `git pull` is then the upgrade)

```bash
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/me/docs-kit        # once per machine
docs-kit init --docs-kit ~/Dev/me/docs-kit                              # --docs-kit .docs-kit forces shim mode
```

## CLI

```text
docs-kit init [ROOT] [--spec openapi.json] [--force] [--without-mise] [--docs-kit PATH]
docs-kit refresh [ROOT] [--spec openapi.json]    # regenerate the generated files
docs-kit check   [ROOT] [--spec openapi.json]    # exit 1 on missing/stale files
docs-kit serve   [ROOT] [--port N] [--host H]   # zensical live-reload; port: --port > $DOCS_PORT > prefer 8010 > first free 8000-8999
docs-kit pull-tasks [ROOT]                       # pin .docs-kit/ to this CLI's version
docs-kit --version
```

## Releasing

```bash
# commit conventional prefixes: feat:=minor  fix:=patch  docs:/chore:=nothing
# GitHub Actions -> Release -> Run workflow -> merge the release PR it opens
# tag + wheel assets + `latest` branch move are automated afterwards
```

Release tags are recreated by the workflow once its release PR is merged (all pre-reset tags were
deliberately deleted, so the next cut restarts versioning from the 0.1.0 baseline). Shim installs
pin `.docs-kit/` to `v$(docs-kit --version)`, so `src/docs_kit/__init__.py` must carry the version
the tag will get - a CLI whose `__version__` matches no published tag (or a tag predating
`shared/mise/`) cannot pin a task layer.

Details (design guarantees, pinning model, task-layer mechanics, CI, dev loop): see [CONTRIBUTING.md](CONTRIBUTING.md).
