# CONTRIBUTING

Everything the [README](README.md) deliberately leaves out: design guarantees, the pinning model, task-layer mechanics, CI, tests, and the release procedure.

## Guarantees

- **Stdlib-only Python; file I/O only for doc generation.** Spec export
  (`go run` / `uv run <api> -spec …`) stays the consuming repository's job.
  The sole subprocesses in the package are the task-layer syncs (`pull-tasks`,
  and `init`'s best-effort shim update), which shell out to `git`.
- **Idempotent and byte-stable**: `refresh` rewrites the whole generated set;
  ordering is sort-stable, runs are byte-equal when nothing changed, and
  semantically-equal specs render identical pages.
- **Generated and authored content never mix**: the kit owns exactly five
  files - the four docs files (`docs/reference/openapi.json` the vendored
  spec, `docs/references/api.md`, `docs/references/endpoints.md`,
  `docs/reference/swagger.html`) plus the consumer CI workflow
  (`.github/workflows/docs.yml`, whose tag-pinned `ref` is stamped with the
  generating CLI's version); everything else under `docs/` and
  `zensical.toml` are scaffold - written by `init`, then owned by the
  consuming repository (`--force` rewrites).
- **`init` installs _and_ repairs**, idempotently: missing pieces are
  re-added, byte-identical files are skipped, hand-edited files are refused
  unless `--force` (generated files should be fixed with `refresh`).
- **`init` adds to `mise.local.toml`, never to your `.mise.toml`.** A missing
  `mise.local.toml` is created with the comment-free opt-in block; an existing
  one gains the block only through a *safe append* - no docs-kit keys present
  and the merged text re-parses as valid TOML (a `[vars]`/`[env]`/
  `[task_config]` header clash would make it invalid, so risky merges are
  refused). Anything else - stale or hand-edited docs-kit keys, unparseable
  merges - leaves the file byte-for-byte untouched and only gets the printed
  copy-paste/merge hint; pasting is then the user's explicit choice.
  `.mise.toml` is **never written**; legacy
  lines from old inits inside `.mise.toml` are quoted in a red cleanup note,
  never rewritten. mise integration is opt-in: without `--with-mise`, none of
  this happens (no task-layer pull, no keys anywhere; docs scaffold only,
  existing files left alone).

## Pinning model

The repository is private (`github.com/ldelarue/docs-kit`); every install
method needs SSH (or HTTPS after `gh auth setup-git`). There is no PyPI
publication - **git refs are the pinning mechanism**. A `latest` branch is
force-moved onto each new release tag by Publish's Move-latest step, in the
run that attached the release's assets - not from a `release`-event workflow,
because the
tag and the `release.created` event that release-please creates with
`GITHUB_TOKEN` start no workflow run at all. Commits on `main` that are not
part of a release are never exposed through `latest`. The wheel on the GitHub
Release is byte-exact for auditable pins.

`uv tool install`/`run` resolve `@latest` at install/run time (`uv tool
upgrade docs-kit` re-resolves); `uv add` records the resolved commit in
`uv.lock` (refresh with `uv lock --upgrade-package docs-kit && uv sync`). For an explicit pin use `@vX.Y.Z` everywhere,
including the CI `ref:` (below) - that pin, not the CLI, is CI's version lock.

**The distribution carries the CLI only** (`uv_build` ships `src/docs_kit/`);
the task layer `shared/mise/` is fetched separately, version-pinned to the
installed CLI - the next section.

## Task layer: opt-in block + pinned `.docs-kit`

`docs-kit init` records where the shared tasks live, in this priority:
`--docs-kit PATH` > `DOCS_KIT` env > `.docs-kit` (shim default). A running
kit checkout is **not** auto-detected: running the CLI from source
(`uv run --no-dev --project ~/Dev/me/docs-kit docs-kit init`) behaves
exactly like the installed wheel and wires the pulled shim. Clone installs
are explicit (`--docs-kit /path/to/docs-kit` or the env).

- **Shim install (`.docs-kit`, relative path)**: init syncs `<repo>/.docs-kit/`
  to tag `v$(docs-kit --version)` as a shallow sparse checkout containing
  **only `/shared/mise/`** (the task file, the sync engine, nothing else),
  then puts the opt-in keys into `mise.local.toml` (created, or appended when
  the merge stays safe; otherwise printed for a manual paste). The sync is
  best-effort: failure is an amber warning, init still exits 0, nothing is
  written that would point mise at a missing include, `mise.local.toml` is
  left for a manual paste of the printed block, and `docs-kit pull-tasks` (or
  `mise run docs:pull-tasks` once any layer exists) retries.
  `DOCS_KIT_SKIP_PULL=1` skips the sync too (used by tests).
- **Checkout install (absolute path, explicit `--docs-kit`)**: nothing is
  fetched - the tasks resolve straight from the full clone (which also
  carries `shared/scripts/`); `git pull` in the clone is the deliberate,
  reviewable upgrade.

`.docs-kit/` stores the pulled layer **only** - no block template lives
there; the block exists just once, as the comment-free string in the CLI,
which init writes into `mise.local.toml` (created/appended when safe) or
prints verbatim when only a manual paste can do:

```toml
[vars]
docs_kit = ".docs-kit"

[env]
DOCS_KIT = "{{ vars.docs_kit }}"

[task_config]
includes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]
```

`mise.local.toml` is git-ignored and mise auto-loads it, so init creating it
is the whole wiring (users who prefer another config file move the keys
there). mise 2026.9.3 has no top-level config-merge to
abuse (`include = [...]` is rejected as an unknown field), which is exactly
why `[task_config].includes` is the mechanism.

Re-running init scans the repo's mise config files for a `docs_kit =` key:
none found -> a missing `mise.local.toml` is created (when the task layer is
in place), an existing config-key-free one is appended to **iff** the merged
text re-parses as TOML, and anything riskier only re-prints the block; keys
found but the block text absent (stale after a kit upgrade, or hand-edited)
-> the block is re-printed with a replace hint, never edited in place. If your
`mise.local.toml` already defines its own `[vars]`/`[env]`/`[task_config]`
tables, init refuses the append and asks you to **merge** the three keys into
them instead of keeping both copies - duplicate table headers are invalid
TOML and mise then skips the whole file (verified on mise 2026.9.3).

**Version semantics**: mise tasks carry none - they are plain TOML resolved
by path and re-read on every `mise run`. The Python package knows its
version, and the layer must follow it. `docs:pull-tasks` lives *in* the
shared `docs.toml` (guard: an absolute `$DOCS_KIT` means a checkout install
-> "nothing to pull", exit 0; the shim path also honours a custom relative
`docs_kit` value). Its body prefers the engine `shared/mise/kit-sync` (which
is part of the pulled payload, so engine updates arrive by pulling the layer);
the inline `git` fallback exists for layers published before the engine, and
bootstrap before any payload exists. Both bootstrap **in place** with
`git init` + `remote add` (`git clone` refuses non-empty directories, and a
half-created shim dir must never block a retry). Before checkout, both
paths `ls-tree` the target tag and **refuse tags that ship no
`shared/mise/` payload** (any tag predating it) - a down-pinned or
version-skewed pull then leaves the working layer untouched instead of wiping
it to empty.
`DOCS_KIT_REPO` overrides the repo URL
(tests use a `file://` mirror); git runs with `BatchMode=yes` SSH so a
missing key fails fast instead of hanging. Task and CLI pin identically:
`v` + `docs-kit --version`.

**Task availability follows the pinned layer**: e.g. `docs:pull-tasks` and
the `kit-sync` engine only exist from the release that ships the current
`shared/mise/` (from the reset baseline onward, every tag carries it). After
bumping the CLI, run `mise run docs:pull-tasks` (or `docs-kit pull-tasks`
when even the block is missing) or the tasks stay a version behind.

`shared/mise` vs `shared/scripts`: the sparse pull contains only
`shared/mise/`. Port leasing for `docs:serve` lives in the CLI itself
(`docs-kit serve`), so shim and checkout installs behave identically;
`shared/scripts/lease-port` is the standalone shell equivalent, kept for
direct use and covered by its own self-test. `.docs-kit/` is a throwaway
artifact: never edit it, `rm -rf` restores it.

## CI

**Consumer repositories** get `.github/workflows/docs.yml` as a GENERATED
kit-owned file: `refresh` rewrites it and `check` fails on any drift, so the
workflow can never silently age. Both jobs check the kit out tag-pinned with
a one-time read-only `DOCS_KIT_PAT` secret and recreate the three gitignored
`mise.local.toml` opt-in keys before mise-action runs (`docs_kit` is the
absolute checkout path under the workspace; committing the same keys to
`.mise.toml` is a harmless duplicate). The `ref: v` stamp is the version of
the CLI that rendered the file - `docs:refresh` after a kit upgrade moves
both jobs together, and a ref that names no published tag fails loudly at
checkout (never hand-bump it). The `check` job guards `mise run docs:check`
on pull requests; `deploy` builds `site/` to GitHub Pages on main. CI
intentionally ignores the floating `latest` branch, and a runner never
depends on what is installed on a machine.

**This repository**: `ci.yml` first runs `hk check --all` (the same steps as
the pre-commit hook - see Development), then pytest plus the
lease-port/shellcheck suite on PRs and main, and uploads the `docs-kit-dist`
wheel artifact. `bump.yml` runs on every push to main: release-please
keeps one release PR open (opening or updating it as conventional commits
accumulate), and on the run whose push merges that PR it tags `vX.Y.Z` and
creates the GitHub Release from the CHANGELOG, then calls `publish.yml`
(`workflow_call`) to attach the wheels and finally force-move `latest` to
the tagged sha. A `concurrency` group keeps two runs
from cutting the same release. Publishing is invoked in-workflow rather than
on `release.created` because events generated with `GITHUB_TOKEN` (the tag
push, the release) never fire other workflows - a called workflow sees the
release regardless of token, so no PAT is required. The merge run is the real
gate: nothing reaches a tag until a human merges the release PR.

## Development

```bash
cd ~/Dev/me/docs-kit
mise install             # hk + ruff join python/uv/shellcheck from .mise.toml
mise run hooks           # hk install --mise -> .git/hooks/pre-commit (per clone)
mise run lint            # hk check --all: ruff format --diff, ruff check, shellcheck
mise run fmt             # hk fix --all: apply ruff format + ruff --fix
mise run test            # pytest (uv)
mise run test-scripts    # shellcheck + lease-port scenarios (also checks shared/mise/kit-sync)
mise run build           # dist/docs_kit-<ver>-py3-none-any.whl + .tar.gz
mise run install-local   # build, then wheel -> docs-kit on PATH (uv tool, --force)
uv run --no-project --with dist/docs_kit-*.whl docs-kit --version   # one-shot, no PATH change
```

`hk.pkl` is the single source for both sides of that gate: the pre-commit hook
fixes staged files (unstaged work stashed and restored), `hk check --all` is
what CI re-runs, and `mise run lint` is the same command locally. Tools come
from mise, not from the hook.

The local wheel is accepted by every install method in the README (build
locally, install locally, nothing pushed). Keep `shared/mise/kit-sync` and
all task bodies POSIX `sh`; shellcheck is part of `test-scripts`, and task
bodies live in **single-line TOML inline tables** (inline tables cannot span
lines, and a literal string can't contain `'` - no `awk`/quoted patterns in
`docs.toml` run bodies).

Tests never touch the network: an autouse fixture sets `DOCS_KIT_SKIP_PULL=1`,
and the git plumbing itself is covered against a local `file://` mirror via
`DOCS_KIT_REPO` (see `tests/test_kit.py::test_pull_tasks_*`).

## Releasing a version (maintainer)

1. Commit with conventional prefixes (`feat:` minor, `fix:` patch; pre-1.0
   `!`/`BREAKING CHANGE` also bump minor; `docs:`/`chore:` release nothing).
   Never bump `pyproject.toml`/`__version__` by hand - the release PR owns them.
   A hand-edited main leaves that PR with nothing to bump, and puts a version
   string on refs no tag ever marked (the `0.2.1` that `latest` briefly carried
   existed only in a file).
2. Pushing conventional commits to `main` fires `bump.yml`: release-please
   opens (or updates) a release PR bumping `pyproject.toml`,
   `__version__`, and the release-please manifest together. This needs the
   repository setting
   Settings → Actions → General → **Allow GitHub Actions to create and approve
   pull requests** - the PR is created by `GITHUB_TOKEN` and fails with
   "GitHub Actions is not permitted to create or approve pull requests"
   otherwise (`gh api repos/ldelarue/docs-kit/actions/permissions/workflow`
   reports the flag). Consequence of that same token: the release PR shows no
   CI checks, and `release.created` fires nothing, which is why the wheels
   attach and `latest` moves inside the called Publish run.
3. Merge the release PR - the only manual step. The push to `main` re-runs
   release-please, which now cuts the release: tag `vX.Y.Z` on the merge
   commit + GitHub Release from the CHANGELOG. Consumers on `@latest` refresh
   via `uv tool upgrade` / `uv lock --upgrade-package docs-kit` and
   `mise run docs:pull-tasks`; pinned consumers re-pin ref+`ref:`.
4. The `publish` job then calls `publish.yml` on the same commit: build,
   `gh release upload vX.Y.Z dist/* --clobber`, and finally force-move the
   `latest` branch onto the tagged sha - so `latest` never points at a
   release without its assets. Re-run Publish manually (pass the tag, leave
   `move_latest_to` empty) to re-attach assets to an existing release.

Dogfood check after release (playground testbed): in `~/Dev/me/golang-api-playground`,
remove any generated docs-kit block from its `.mise.toml`, re-run
`docs-kit init`, apply the printed one-liner, then `mise run docs:serve`
and `mise run docs:check`.
