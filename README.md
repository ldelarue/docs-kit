# docs-kit

docs-kit scaffolds, regenerates, and CI-verifies a **Zensical + Diátaxis** docs site for an API repository, generated from its own `openapi.json`, with a `docs:*` mise task layer version-locked to the CLI. The point is to keep API docs honest without hand-maintenance: the kit derives the reference pages straight from the spec, owns only the generated files so your authored guides are never overwritten, and the `docs:check` gate fails the build when docs go stale, so the published docs can't drift from the API they describe.

## Install (private repo: needs an SSH key, or `gh auth setup-git`)

```bash
uv tool install --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@latest" docs-kit
uv tool install --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@vX.Y.Z" docs-kit   # pinned
uv add "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@latest"                            # uv-project dependency
```

## Setup in a repository

```bash
mise run openapi                       # your repo's own spec-export task: produce openapi.json first
docs-kit init                          # scaffolds docs; creates the keys below in mise.local.toml
                                       # when it has none, else prints this block to paste
# (add --without-mise to scaffold docs only: no .docs-kit/ layer, no task wiring)
```

```toml
# the docs-kit keys (init writes them into a missing mise.local.toml; if you
# already have these tables somewhere, merge the keys - one of each header
# only, a duplicate is invalid TOML):
[vars]
docs_kit = ".docs-kit"

[env]
DOCS_KIT = "{{ vars.docs_kit }}"

[task_config]
includes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]
```

```bash
mise run docs:refresh && mise run docs:build   # then commit; docs:* tasks are live
```

`init` also generates `.github/workflows/docs.yml` (kit-owned: refresh rewrites it,
check fails on drift). Its two jobs check docs-kit out tag-pinned at the version that
generated the workflow, and recreate the gitignored `mise.local.toml` keys CI never
has. One-time CI setup per consumer repo: a fine-grained `DOCS_KIT_PAT` secret
(contents: read on ldelarue/docs-kit) plus Pages source = "GitHub Actions".

`docs-kit init` writes that block into a missing `mise.local.toml` (mise auto-loads it; init
git-ignores it), or appends it to an existing one when the merged file stays valid TOML.
If your `mise.local.toml` already carries tables or docs-kit keys init will not merge into,
it is never rewritten - init just re-prints the block for a manual paste/merge, and does so
again when pasted keys went stale (older kit version or hand edits). `.docs-kit/` holds only
the pinned `shared/mise/` task layer that init pulls (tag `v$(docs-kit --version)`); the pull
is best-effort - until a matching tag exists it leaves `.docs-kit/` empty with a warning and
writes no `mise.local.toml` (a broken include would not load), so run init from a dev
checkout (`--docs-kit`) meanwhile.

## Tasks (`mise run docs:*`)

```text
docs:init         docs-kit init (re-run to re-apply the keys to mise.local.toml and re-pin the layer)
docs:refresh      mise run openapi, then docs-kit refresh (regenerate the 5 owned files,
                  docs pages + the CI workflow - refresh also re-stamps the workflow's kit `ref`)
docs:build        refresh, then zensical build --clean -> site/
docs:serve        live-reload on http://127.0.0.1:8010, or the next free 8000-8999 port if taken
                  (pin exactly with DOCS_PORT=...)
docs:check        CI gate: fails on stale docs or an uncommitted diff
docs:pull-tasks   re-pin .docs-kit/ (shared/mise) to the installed CLI's version
```

## Update

```bash
uv tool upgrade docs-kit && mise run docs:pull-tasks && mise run docs:refresh && mise run docs:check
# refresh is what moves the workflow's tag-pinned kit ref to the new version
```

## Dev checkout

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
# pushing to main opens/updates a release PR; merging that PR is the one manual
# step: same run cuts the tag + GitHub Release, attaches wheels, moves `latest`
```

Release tags are recreated by the workflow once its release PR is merged (all pre-reset tags were
deliberately deleted, so the next cut restarts versioning from the 0.1.0 baseline). Shim installs
pin `.docs-kit/` to `v$(docs-kit --version)`, so `src/docs_kit/__init__.py` must carry the version
the tag will get - a CLI whose `__version__` matches no published tag (or a tag predating
`shared/mise/`) cannot pin a task layer.

Details (design guarantees, pinning model, task-layer mechanics, CI, dev loop): see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Documentation and other creative content in this repository are licensed under the
[Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/)
(CC BY 4.0). See [LICENSE](LICENSE).
