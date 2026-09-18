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

The `docs:*` tasks live in `shared/mise/docs.toml` and are attached to a
consuming repository by path:

```toml
[vars]
docs_kit = ".docs-kit"                        # relative = repository-local shim

[env]
DOCS_KIT = "{{ vars.docs_kit }}"

[task_config]
includes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]
```

A limitation must be stated precisely: **mise tasks carry no version
semantics.** They are plain TOML resolved by a path and re-read on every
`mise run`. The Python package, however, knows its version
(`docs-kit --version`), and the task layer must follow it. The mechanism
below closes that gap.

`docs-kit init --docs-kit .docs-kit` writes the task below into the
consuming repository's `.mise.toml` (a helper task must exist before the
first download, so it lives in the consuming config, not in the kit file);
it is shown here for reference and for manual installs. It pins a shallow,
sparse checkout (only `shared/`, ~200 KB) of the tag matching the installed
CLI:

```toml
[tasks."docs:kit-sync"]
description = "Pin the .docs-kit task layer to the installed docs-kit version"
run = '''
set -eu
ver="$({ docs-kit --version 2>/dev/null || uv run --no-dev docs-kit --version; } | awk '{print $2}')"
v="v$ver"
if [ ! -d .docs-kit ]; then
  git clone -q -c advice.detachedHead=false --depth 1 --branch "$v" \
    --filter=blob:none --sparse git@github.com:ldelarue/docs-kit.git .docs-kit
  git -C .docs-kit sparse-checkout set shared
fi
if [ "$(git -C .docs-kit describe --tags --exact-match 2>/dev/null || true)" != "$v" ]; then
  git -C .docs-kit fetch -q --depth 1 origin "+refs/tags/$v:refs/tags/$v"
  git -C .docs-kit -c advice.detachedHead=false checkout -q "$v"
fi
echo "docs task layer pinned at $v"
'''
```

The task reads the version of the installed CLI and checks `.docs-kit` out
at exactly that tag (`latest` or a pinned `@vX.Y.Z` — either way `$ver` is a
released number) using the same SSH authentication as everything else.
`.docs-kit` is a build artifact: never edit it, and add it to `.gitignore`.

One-time setup of a consuming repository (method 1 style):

```bash
cd ~/Dev/my-new-api
mise run openapi                    # produce openapi.json first
docs-kit --version                  # or uv tool run / uv run, per section 1
docs-kit init --docs-kit .docs-kit  # writes the [vars]/[env]/[task_config]
                                    # block, the docs:kit-sync task, and the
                                    # .docs-kit/ gitignore entry
mise run docs:kit-sync && mise run docs:refresh && mise run docs:build
```

Upgrades require exactly one decision — bump the CLI ref:

```bash
uv tool install --from "docs-kit @ git+ssh://…git@latest" docs-kit   # re-resolve latest
# (or change an @vX.Y.Z pin / lock upgrade, per section 1)
mise run docs:kit-sync && mise run docs:refresh && git diff docs/
```

The task layer cannot drift from the CLI: both come from the same release,
and the task file is checked out byte-exactly from `v$(docs-kit --version)`.
Constraints: `.docs-kit` requires **v0.2.0 or newer** (first tag carrying
`shared/mise/docs.toml`), and the set of available tasks depends on the
pinned layer (e.g. `docs:serve` arrives with the release after v0.2.1).
CI is independent of this mechanism in both directions: the consumer
workflow checks out the kit by its own explicit `ref:` tag (see CI), so a
runner never depends on what is installed on a given machine, and moving
the `latest` ref affects no CI result by itself.

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
| `docs-kit init [--force] [--docs-kit PATH]` | Full install/repair, idempotent. Writes the authored scaffold (`docs/index.md`, `docs/tutorials\|guides\|explanation\|references/index.md`, `zensical.toml`, the CI workflow `.github/workflows/docs.yml`), the four generated files, the mise integration block (repairing a deleted one), and the `.gitignore` entries (`site/`, `.cache/`). Existing files that differ from what `init` would generate are listed and refused unless `--force`; generated files should be updated with `refresh`, not `--force`. `--docs-kit PATH` sets the value recorded as `vars.docs_kit` (required for method-1 installs: `--docs-kit .docs-kit`, which additionally writes the `docs:kit-sync` task and the matching `.gitignore` entry; a wheel run with no checkout records a placeholder and prints a warning). |
| `docs-kit refresh` | The routine command: regenerates the four generated files from the current `openapi.json`. Run it, then review `git diff docs/`, after a spec change, an endpoint change, or a kit upgrade. |
| `docs-kit check` | Renders in memory and byte-compares; exits 1, names every missing or stale file, and prints `run \`mise run docs:refresh\` and commit the result`. This is the command invoked by CI and git hooks. |
| `docs-kit --version` | The version the release-please release assigned; also the value `docs:kit-sync` reads. |

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
| `docs:serve` | live-reload serve on `127.0.0.1:$PORT` — prefers **8010**, otherwise the first free port in 8000–8999 (via `shared/scripts/lease-port`); pinned exactly with `DOCS_PORT=…`. The port machinery is local-only; CI never serves. |
| `docs:check` | `mise run openapi`, `docs-kit check`, and `git diff --exit-code -- docs openapi.json` (fails when a refresh was not committed) |

## CI

**Consumer repositories** receive the scaffolded
`.github/workflows/docs.yml` from `init`: both jobs check the kit out
tag-pinned (`ref: vX.Y.Z`, with a read-only private `DOCS_KIT_PAT` secret —
one time per repository) and write the path into `mise.local.toml`. The
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
   `mise run docs:kit-sync`; consumers with an explicit pin re-pin and bump
   the CI `ref:` value.
