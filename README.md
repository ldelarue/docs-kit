# docs-kit

Generate and verify the **Zensical + Diátaxis** documentation site for an API
repository from its `openapi.json`. The CLI (`docs-kit`) is pure-file-I/O
Python, stdlib-only; the convenience layer is a small set of shared `mise`
tasks (`docs:*`) that live with the kit — not duplicated per repo. Docs stay
up to date because a stale site is a red CI check, not because anyone
remembers.

## Guarantees

- **Stdlib only, zero subprocesses** in the Python code: spec export
  (`go run` / `uv run <your-api> -spec …`) stays the consumer repo's job;
  the kit only reads `openapi.json` and writes files.
- **Idempotent, byte-stable**: `refresh` rewrites the whole generated set;
  ordering is sort-stable, so runs are byte-equal when nothing changed and
  semantically-equal specs render identical pages.
- **Generated vs authored never mix**: the kit owns exactly four files
  (table below). Your authored markdown is the only other input.
- **`init` installs _and_ repairs**, idempotently: missing pieces are
  re-added, byte-identical files skipped, hand-edited files refused without
  `--force`.

The repo is private (`github.com/ldelarue/docs-kit`); all three install ways
below use your SSH key (or HTTPS after `gh auth setup-git`). There is no
PyPI, and GitHub has no PyPI/pip index — **git tags are the pin mechanism.**

---

## 1. Install the CLI with `uv`

```bash
# recommended: a pinned release on PATH (tool = exactly this use case)
uv tool install --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@vX.Y.Z" docs-kit
docs-kit --version        # docs-kit X.Y.Z

# or as a dependency of your python/uv project
uv add "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@vX.Y.Z"
uv run docs-kit --version

# or run it ephemerally, never installed
uvx --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@vX.Y.Z" docs-kit --version
```

`@vX.Y.Z` is optional (omitting it follows `main`) — strongly prefer it:
the tag is what makes the install reproducible and reviewable.
Prefer a byte-exact artifact? Every GitHub Release carries the built wheel +
sdist:

```bash
gh release download vX.Y.Z --pattern '*.whl' --repo ldelarue/docs-kit
uv tool install --from ./docs_kit-X.Y.Z-py3-none-any.whl docs-kit   # or: uv add ./docs_kit-*.whl
```

Upgrading = change `vX.Y.Z` and re-run one command
(`uv tool upgrade docs-kit`, or `uv lock --upgrade` after re-pinning with
`uv add`).

**The wheel carries the CLI only.** The task layer (`shared/mise/docs.toml` +
`shared/scripts/`) is packaging-excluded (uv_build ships `src/docs_kit/`
only). That's exactly what way 2 is about.

## 2. Shared mise tasks, version-locked to your installed CLI

The `docs:*` tasks come from `shared/mise/docs.toml` in a checkout, included
by path:

```toml
[vars]
docs_kit = ".docs-kit"                        # relative = repo-local shim

[env]
DOCS_KIT = "{{ vars.docs_kit }}"

[task_config]
includes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]
```

You are right about the tricky part and there is nothing to correct:
**mise tasks have no notion of versions.** They are plain TOML referenced by
a path, and every `mise run` reads that path live. The *CLI* knows its
version (`docs-kit --version`) — the task layer must follow it.

The lock is one extra task you paste in **once** (it must exist before the
first download, hence it lives in your own config, not in the kit file):

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

What it does: reads the **installed CLI's version**, then makes `.docs-kit`
a shallow, sparse (only `shared/`, ~200 KB) git clone checked out at exactly
that tag — same auth as everything else (your SSH key). Never edit or
commit `.docs-kit`; add it to `.gitignore`.

One-time consumer setup (way-1 style):

```bash
cd ~/Dev/my-new-api
mise run openapi                    # produce openapi.json first
docs-kit --version                  # or uv run / uvx, per way 1
# add the [vars]/[env]/[task_config] block + docs:kit-sync above,
# ".docs-kit" in .gitignore (docs-kit init --docs-kit .docs-kit writes all
# of it except the sync task and the gitignore entry)
docs-kit init --docs-kit .docs-kit
mise run docs:kit-sync && mise run docs:refresh && mise run docs:build
```

Then upgrades are one move: bump the CLI pin (`uv tool install --from …@v0.4.0`,
or the wheel URL) and run

```bash
mise run docs:kit-sync && mise run docs:refresh && git diff docs/
```

The task layer **cannot drift from the CLI**: both are the same release, the
task file is byte-checked-out from `v$({docs-kit --version})`. Notes:
`.docs-kit` needs ≥ **v0.2.0** (first tag carrying `shared/mise/docs.toml`);
which tasks exist depends on the pinned layer (e.g. `docs:serve` arrives with
the release after v0.2.1). CI does not use this trick — the scaffolded
consumer workflow checks the kit out by its own `ref:` tag (see CI below),
so a runner never depends on what happens to be installed on some machine.

## 3. Use the whole project locally (full clone)

For developing the kit itself, dogfooding template changes, or when you want
the source rather than a shim:

```bash
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/me/docs-kit   # once per machine
```

A consumer pointed at a full clone needs no sync task — `init` records the
real checkout and `git pull` is the (deliberate, human) upgrade:

```bash
# consumer repo
mise run openapi
uv run --no-dev --project ~/Dev/me/docs-kit docs-kit init   # writes docs_kit = absolute clone path
mise run docs:refresh && mise run docs:build

# upgrade whenever you decide (tasks re-read the clone on every mise run):
cd ~/Dev/me/docs-kit && git pull            # or git checkout vX.Y.Z to hold a version
cd ~/Dev/my-new-api && mise run docs:refresh && git diff docs/ && mise run docs:check
```

The clone path is the only machine-specific value; override per machine via
`mise.local.toml` (gitignore it): `[vars] docs_kit = "/other/path/docs-kit"`.
`init` records its own checkout (`--docs-kit` overrides); don't use `~` —
mise includes don't expand it. Kit development loop + built-package shortcuts:

```bash
cd ~/Dev/me/docs-kit
mise run test / test-scripts        # pytest + shellcheck/lease-port suite
mise run build                      # dist/docs_kit-<ver>-py3-none-any.whl + .tar.gz
mise run install-local              # wheel → docs-kit on PATH (uv tool, --force)
uv run --no-project --with dist/docs_kit-*.whl docs-kit --version   # one-shot, no PATH change
```

---

## How to use the CLI (`docs-kit`)

All commands share: `docs-kit <command> [ROOT] [--spec openapi.json]`
(ROOT = target repo, default cwd; `--spec` = spec path relative to ROOT).

| command | what it does |
| --- | --- |
| `docs-kit init [--force] [--docs-kit PATH]` | Full install/repair, idempotent: writes the authored scaffold (`docs/index.md`, `docs/tutorials|guides|explanation|references/index.md`, `zensical.toml`, CI workflow `.github/workflows/docs.yml`), the four generated files, the mise integration block (or repairs a deleted one), and `.gitignore` entries (`site/`, `.cache/`). Existing files differing from what init would write are listed and **refused** unless `--force`; generated files should be fixed with `refresh`, not `--force`. `--docs-kit PATH` is what gets recorded as `vars.docs_kit` (needed for way-1 installs: `--docs-kit .docs-kit`; a wheel run with no checkout would otherwise record a placeholder and warn). |
| `docs-kit refresh` | The daily driver: regenerates the four generated files from the current `openapi.json`. Run it (and review `git diff docs/`) after changing the spec, the endpoint code/prose sources, or the kit version. |
| `docs-kit check` | Renders in memory and byte-compares; exit 1 + names every missing/stale file and prints `run mise run docs:refresh and commit the result`. This is what CI and git hooks run. |
| `docs-kit --version` | The version release-please tagged the wheel/checkout with — also what `docs:kit-sync` reads. |

Generated files the kit **owns** (never hand-edit; your edits are lost on
next refresh):

| file | content |
| --- | --- |
| `docs/references/openapi.json` | the vendored spec |
| `docs/references/api.md` | OpenAPI → reference page |
| `docs/references/endpoints.md` | endpoint index |
| `docs/reference/swagger.html` | Swagger UI page |

Everything else under `docs/` (index, tutorials, guides, explanation stubs +
whatever you add), `zensical.toml` and the CI workflow are **scaffold**:
written by `init`, yours to edit afterwards (init then leaves them;
`--force` re-writes).

Daily example (after changing an endpoint):

```bash
mise run openapi        # your repo's spec export task (go run / uv run …)
mise run docs:refresh   # regenerate the four owned files
git diff docs/ && mise run docs:check && git add docs/ && git commit -m "docs: update ..."
```

## The task layer (`mise run docs:*`)

Provided by the included file (`$DOCS_KIT/shared/mise/docs.toml`, task
bodies resolve your `docs-kit` on `PATH`, else run the checkout through
`uv run --no-dev --project`):

| task | runs |
| --- | --- |
| `docs:init` | `docs-kit init` (see CLI) |
| `docs:refresh` | `mise run openapi` then `docs-kit refresh` |
| `docs:build` | refresh, then `zensical build --clean` → `site/` |
| `docs:serve` | live-reload serve on `127.0.0.1:$PORT` — prefers **8010**, else first free port in 8000–8999 (via `shared/scripts/lease-port`); pin exactly with `DOCS_PORT=….` Port machinery is local-only — CI never serves. |
| `docs:check` | `mise run openapi`, `docs-kit check`, and `git diff --exit-code -- docs openapi.json` (catches forget-to-commit refreshes) |

## CI

**Consumer repos** get a scaffolded `.github/workflows/docs.yml` from `init`:
both jobs check the kit out **tag-pinned** (`ref: vX.Y.Z`, private
read-only `DOCS_KIT_PAT` secret — one-time per repo) and write the path into
`mise.local.toml`; `check` guards `docs:check` on PRs, `deploy` builds
`site/` to GitHub Pages on `main`. **Bump the `ref:` in both jobs at each
kit release** — that pin, not the CLI, is CI's version lock.

**This repo:** `ci.yml` — pytest + lease-port self-tests on every PR and
`main` + wheels as `docs-kit-dist` artifact; `release.yml` — manual
release-please dispatch; `publish.yml` — attaches wheels to each GitHub
Release.

## Releasing a version (maintainer)

1. Commit with conventional prefixes (`feat:` minor, `fix:` patch;
   pre-1.0 `!`/`BREAKING CHANGE` also bump minor; `docs:`/`chore:` release
   nothing).
2. GitHub Actions → Release → **Run workflow** (nothing is automatic): opens
   or updates a release PR bumping `pyproject.toml`, `__version__` and the
   release-please manifest together.
3. Merge → tag `vX.Y.Z` + GitHub Release + wheel assets. Consumers then
   re-pin the CLI (way 1) or bump CI `ref:` — and `mise run docs:kit-sync`
   silently follows the CLI's new version.
