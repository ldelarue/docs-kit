# docs-kit

Generate and verify the **Zensical + Diátaxis** documentation site for an API
repository from its `openapi.json`. The CLI (`docs-kit`) is pure-file-I/O
Python, stdlib-only; the convenience layer is a small set of shared `mise`
tasks (`docs:*`) that live with the kit rather than being duplicated per
repository. Documentation stays current because a stale site fails a CI
check.

## Guarantees

- **Stdlib only, zero subprocesses** in the Python code: spec export
  (`go run` / `uv run <api> -spec …`) remains the responsibility of the
  consuming repository; the kit only reads `openapi.json` and writes files.
- **Idempotent and byte-stable**: `refresh` rewrites the whole generated
  set; ordering is sort-stable, so runs are byte-equal when nothing changed
  and semantically-equal specs render identical pages.
- **Generated and authored content never mix**: the kit owns exactly four
  files (table below); authored markdown is the only other input.
- **`init` installs _and_ repairs**, idempotently: missing pieces are
  re-added, byte-identical files are skipped, and hand-edited files are
  refused unless `--force` is passed.

The repository is private (`github.com/ldelarue/docs-kit`); all three
install methods below use an SSH key (or HTTPS after `gh auth setup-git`).
There is no PyPI publication, and GitHub provides no PyPI/pip index —
**git refs are the pinning mechanism.**

---

## 1. Install the CLI with `uv`

A git branch named `latest` is force-updated to the most recent release tag
by `publish.yml`; commits on `main` that are not part of a release are never
exposed through it. This is the default way to consume the CLI without
choosing a version:

```bash
# floating on the latest release:
uv tool install --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@latest" docs-kit
uv add "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@latest"              # uv-project dependency
uv tool run --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@latest" docs-kit --version

docs-kit --version
```

Version and refresh semantics per installation style:

- `uv tool install` / `uv tool run` resolve `@latest` at install/run time;
  refresh the pinned commit with `uv tool upgrade docs-kit`.
- `uv add` records the **resolved commit** in `uv.lock`, so builds stay
  reproducible even while the ref floats; pull in a newer release with
  `uv lock --upgrade-package docs-kit && uv sync`.

For a frozen, auditable pin, replace `@latest` with a release tag (or use
the wheel shipped as a GitHub Release asset, which is byte-exact):

```bash
uv tool install --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@vX.Y.Z" docs-kit
gh release download vX.Y.Z --pattern '*.whl' --repo ldelarue/docs-kit
uv tool install --from ./docs_kit-X.Y.Z-py3-none-any.whl docs-kit   # or: uv add ./docs_kit-*.whl
```

**The distribution carries the CLI only.** The task layer
(`shared/mise/docs.toml` + `shared/scripts/`) is packaging-excluded
(uv_build ships `src/docs_kit/` only); the next section covers installing it.

## 2. Shared mise tasks, version-locked to the installed CLI

The `docs:*` tasks live in the kit as `shared/mise/docs.toml`. In shim mode
a consuming repository receives **no tracked docs-kit lines in
`.mise.toml`**: `docs-kit init --docs-kit .docs-kit` writes the entire
integration — `[vars]`, `[env]`, `[task_config].includes` and the fetch
task — into `mise.local.toml` (a native mise per-machine file that init
also adds to `.gitignore`, alongside `.docs-kit/`). Put personal mise
overrides in the same file, above the generated block.

The layer is fetched into `.docs-kit/` as a shallow, sparse checkout that
contains **only `/shared/mise/`** — the task file and the sync engine,
nothing else of the repository.

A limitation must be stated precisely: **mise tasks carry no version
semantics.** They are plain TOML resolved by a path and re-read on every
`mise run`. The Python package, however, knows its version
(`docs-kit --version`), and the task layer must follow it. The generated
`mise.local.toml` closes that gap; its fetch task is:

```toml
[tasks."docs:pull-tasks"]
description = "Fetch docs-kit task files (shared/mise) at the installed CLI's tag"
run = '''
set -eu
if [ -f .docs-kit/shared/mise/kit-sync ]; then
  exec sh .docs-kit/shared/mise/kit-sync .docs-kit
fi
ver="$({ docs-kit --version 2>/dev/null || uv run --no-dev docs-kit --version; } 2>/dev/null | awk '{print $2}')"
if [ -z "$ver" ]; then
  echo "pull-tasks: no docs-kit on PATH or uv project here; install the CLI first (kit README section 1)" >&2
  exit 1
fi
v="v$ver"
if [ ! -d .docs-kit ]; then
  git clone -q -c advice.detachedHead=false --depth 1 --branch "$v" \
    --filter=blob:none --sparse git@github.com:ldelarue/docs-kit.git .docs-kit
fi
if [ "$(git -C .docs-kit describe --tags --exact-match 2>/dev/null || true)" != "$v" ]; then
  git -C .docs-kit fetch -q --depth 1 origin "+refs/tags/$v:refs/tags/$v"
  git -C .docs-kit -c advice.detachedHead=false checkout -q "$v"
fi
git -C .docs-kit -c advice.detachedHead=false sparse-checkout set --no-cone '/shared/mise/' 2>/dev/null || true
echo "docs task layer pinned at $v (frozen fallback; kit-sync engine file arrives with a later release)"
'''
```

Task definition and logic are separated deliberately: the canonical engine
lives **in the pulled payload itself** (`shared/mise/kit-sync`) and is
therefore maintained in one place and upgraded by pulling the layer; the
snippet above (which must run before the payload exists, hence it is
generated into the consumer's local config) delegates to that engine as soon
as it is present. The remaining inline body is a frozen fallback for layers
published before the engine existed (v0.2.1 and older) and disappears from
behaviour—not from the file—once the pin moves to a newer release.

Pinned fetch semantics: the task reads the version of the installed CLI
(`latest` or `@vX.Y.Z` — `$ver` is always a released number) and checks
`.docs-kit` out at exactly that tag, same SSH authentication as everything
else; it also renormalises the sparse sparsity to `/shared/mise/` on every
run. `.docs-kit` is a throwaway artifact: never edit it (git checkout will
not overwrite hand edits there, and one `rm -rf` restores it).

One-time setup of a consuming repository:

```bash
cd ~/Dev/my-new-api
mise run openapi                    # produce openapi.json first
docs-kit --version                  # or uv tool run / uv run, per section 1
docs-kit init --docs-kit .docs-kit  # writes mise.local.toml + gitignore
                                    # entries; .mise.toml stays docs-kit-free
mise run docs:pull-tasks && mise run docs:refresh && mise run docs:build
```

Re-running `init` in shim mode also removes any previously generated
docs-kit lines from `.mise.toml` (vars/env/include, older sync tasks) — they
live in `mise.local.toml` now.

Upgrades require exactly one decision — bump the CLI ref:

```bash
uv tool install --from "docs-kit @ git+ssh://…git@latest" docs-kit   # re-resolve latest
# (or change an @vX.Y.Z pin / lock upgrade, per section 1)
mise run docs:pull-tasks && mise run docs:refresh && git diff docs/
```

The task layer cannot drift from the CLI: both come from the same release,
and the task file is checked out byte-exactly from `v$(docs-kit --version)`.
Constraints: `.docs-kit` requires **v0.2.0 or newer** (first tag carrying
`shared/mise/docs.toml`); the set of available tasks follows the pinned
layer (e.g. `docs:serve` arrives with the first release after v0.2.1).
Because the pull is limited to `shared/mise/`, tasks that reach into
`shared/scripts/` — the lease-port helper of `docs:serve` — fall back to
their fixed default (port 8010 on shims; full port leasing requires the
clone method). CI is independent of this mechanism in both directions: the
consumer workflow checks out the kit by its own explicit `ref:` tag and
writes its own `mise.local.toml`, so a runner never depends on what is
installed on a machine, and moving the `latest` ref affects no CI result by
itself.

## 3. Use the whole project locally (full clone)

For developing the kit itself and for dogfooding template changes, a full
clone provides both sources and tasks; `init` records the real checkout and
`git pull` is the deliberate, human reviewable upgrade:

```bash
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/me/docs-kit   # once per machine

# consuming repository
mise run openapi
uv run --no-dev --project ~/Dev/me/docs-kit docs-kit init   # writes docs_kit = absolute clone path
mise run docs:refresh && mise run docs:build

# upgrade after review (tasks re-read the clone on every mise run):
cd ~/Dev/me/docs-kit && git pull                # or git checkout vX.Y.Z to hold a version
cd ~/Dev/my-new-api && mise run docs:refresh && git diff docs/ && mise run docs:check
```

The clone path is the only machine-specific value; override per machine via
`mise.local.toml` (gitignored): `[vars] docs_kit = "/other/path/docs-kit"`.
`init` records its own checkout (`--docs-kit` overrides); `~` is not
expanded in mise `includes`, so paths must be literal. Kit development loop
and built-package shortcuts:

```bash
cd ~/Dev/me/docs-kit
mise run test / test-scripts        # pytest + shellcheck/lease-port suite
mise run build                      # dist/docs_kit-<ver>-py3-none-any.whl + .tar.gz
mise run install-local              # wheel → docs-kit on PATH (uv tool, --force)
uv run --no-project --with dist/docs_kit-*.whl docs-kit --version   # one-shot, no PATH change
```

The local wheel is also accepted by section 1 (`uv tool install --from` /
`uv add` accept a local path), which completes the offline loop: build
locally, install locally, nothing pushed.

---

## How to use the CLI (`docs-kit`)

All commands share the form `docs-kit <command> [ROOT] [--spec openapi.json]`
(ROOT = target repository, default cwd; `--spec` = spec path relative to
ROOT).

| command | effect |
| --- | --- |
| `docs-kit init [--force] [--docs-kit PATH]` | Full install/repair, idempotent. Writes the authored scaffold (`docs/index.md`, `docs/tutorials\|guides\|explanation\|references/index.md`, `zensical.toml`, the CI workflow `.github/workflows/docs.yml`), the four generated files, the mise integration block (repairing a deleted one), and the `.gitignore` entries (`site/`, `.cache/`). Existing files that differ from what `init` would generate are listed and refused unless `--force`; generated files should be updated with `refresh`, not `--force`. `--docs-kit PATH` sets the value recorded as `vars.docs_kit` (required for method-1 installs: `--docs-kit .docs-kit`, in shim mode init writes `mise.local.toml` (vars/env/include + the `docs:pull-tasks` fetch task) and the matching `.gitignore` entries, and strips previously generated shim lines from `.mise.toml`; a wheel run with no checkout records a placeholder and prints a warning). |
| `docs-kit refresh` | The routine command: regenerates the four generated files from the current `openapi.json`. Run it, then review `git diff docs/`, after a spec change, an endpoint change, or a kit upgrade. |
| `docs-kit check` | Renders in memory and byte-compares; exits 1, names every missing or stale file, and prints `run \`mise run docs:refresh\` and commit the result`. This is the command invoked by CI and git hooks. |
| `docs-kit --version` | The version the release-please release assigned; also the value `docs:pull-tasks` reads. |

Generated files owned by the kit (hand edits are overwritten on the next
`refresh`):

| file | content |
| --- | --- |
| `docs/references/openapi.json` | the vendored spec |
| `docs/references/api.md` | OpenAPI → reference page |
| `docs/references/endpoints.md` | endpoint index |
| `docs/reference/swagger.html` | Swagger UI page |

Everything else under `docs/` (index, section stubs and additional authored
pages), `zensical.toml`, and the CI workflow are **scaffold**: written by
`init`, then owned by the consuming repository (left untouched afterwards;
`--force` rewrites them).

Routine example (after changing an endpoint):

```bash
mise run openapi        # the repository's own spec-export task (go run / uv run …)
mise run docs:refresh   # regenerate the four owned files
git diff docs/ && mise run docs:check && git add docs/ && git commit -m "docs: update ..."
```

## The task layer (`mise run docs:*`)

Provided by the included file (`$DOCS_KIT/shared/mise/docs.toml`); task
bodies resolve a `docs-kit` binary on `PATH`, otherwise they run the
checkout through `uv run --no-dev --project`:

| task | runs |
| --- | --- |
| `docs:init` | `docs-kit init` (see above) |
| `docs:refresh` | `mise run openapi`, then `docs-kit refresh` |
| `docs:build` | refresh, then `zensical build --clean` → `site/` |
| `docs:serve` | live-reload serve on `127.0.0.1:$PORT` — prefers **8010**, otherwise the first free port in 8000–8999 (via `shared/scripts/lease-port`, fixed **8010** on uv-shims where only `shared/mise/` was pulled); pinned exactly with `DOCS_PORT=…`. The port machinery is local-only; CI never serves. |
| `docs:pull-tasks` | uv-shim consumers only, defined in `mise.local.toml` rather than in the payload: fetches `.docs-kit/shared/mise/` at the installed CLI's tag (section 2) |
| `docs:check` | `mise run openapi`, `docs-kit check`, and `git diff --exit-code -- docs openapi.json` (fails when a refresh was not committed) |

## CI

**Consumer repositories** receive the scaffolded
`.github/workflows/docs.yml` from `init`: both jobs check the kit out
tag-pinned (`ref: vX.Y.Z`, with a read-only private `DOCS_KIT_PAT` secret —
one time per repository) and write `mise.local.toml` in full
(`[vars]`, `[env]` and the `[task_config]` include — the same shape `init`
generates for shims). The
`check` job guards `docs:check` on pull requests; the `deploy` job builds
`site/` to GitHub Pages on `main`. Bump the `ref:` in both jobs at each kit
release — that pin, not the CLI, is CI's version lock; CI intentionally
ignores the floating `latest` ref.

**This repository:** `ci.yml` runs pytest and the lease-port self-tests on
every pull request and on `main`, and uploads wheels as the
`docs-kit-dist` artifact; `release.yml` is the manual release-please
dispatch; `publish.yml` attaches the wheels to each GitHub Release and moves
the `latest` branch to that release.

## Releasing a version (maintainer)

1. Commit with conventional prefixes (`feat:` minor, `fix:` patch; pre-1.0
   `!`/`BREAKING CHANGE` also bump minor; `docs:`/`chore:` release nothing).
2. GitHub Actions → Release → **Run workflow** (nothing is automatic): opens
   or updates a release PR bumping `pyproject.toml`, `__version__`, and the
   release-please manifest together.
3. Merge → tag `vX.Y.Z` + GitHub Release + wheel assets; `publish.yml` moves
   the `latest` branch to the tag. Consumers using `@latest` refresh via
   `uv tool upgrade` / `uv lock --upgrade-package docs-kit` and
   `mise run docs:pull-tasks`; consumers with an explicit pin re-pin and bump
   the CI `ref:` value.
