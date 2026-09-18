# docs-kit

Generate and verify the **Zensical + Diátaxis** documentation site for an API
repository from its `openapi.json`, driven by `mise` tasks in the consuming
repo. Seeded from the `docs-playground` prototype; the CLI-spec machinery from
the prototype is intentionally **not** part of this kit (OpenAPI-only by
design).

## Guarantees

- **Stdlib only, zero subprocesses** in the Python code: the kit is pure file
  I/O. Spec export (`go run` / `uv run`) belongs to the consuming repo's
  `mise` tasks, so the kit never needs a Go or project-Python toolchain.
- **Idempotent and byte-stable**: `refresh` rewrites generated files in whole;
  ordering is sort-stable so `refresh` never rewrites files unchanged and
  semantically-equal specs (e.g. the Go and Python implementations sharing one
  contract) render the same pages regardless of key order.
- **Generated and authored content never mix**: the kit owns
  `docs/references/endpoints.md`, `docs/references/api.md`,
  `docs/reference/swagger.html`, `docs/reference/openapi.json` wholesale; your
  authored markdown is its only other input.

## Commands (run in the target API repo, or pass the repo dir)

| command | effect |
| --- | --- |
| `docs-kit init [--force] [--docs-kit PATH]` | install **or repair** the docs integration: writes missing files, skips byte-identical ones, (re-)adds the `.mise.toml` block and `.gitignore` entries if they were deleted; refuses only if existing files differ from generated content — `--force` overwrites those |
| `docs-kit refresh [--spec openapi.json]` | re-export step is done by the repo (`mise run openapi`), then the kit copies + renders the four generated files |
| `docs-kit check` | renders in memory and byte-compares against the repo; exits non-zero on missing/stale files |

`init` requires `openapi.json` to exist first (it reads `info.title` for the
site title): run the repo's `mise run openapi` before `docs-kit init`.

## Consuming repos: shared tasks, zero duplication

The `docs:*` **task definitions live only here**, in `shared/mise/docs.toml`.
A consumer repo holds no copies of them — its `.mise.toml` gains just a
pointer (written by `docs-kit init`):

```toml
[vars]
docs_kit = "/Users/you/Dev/me/docs-kit"          # where YOUR clone lives

[env]
DOCS_KIT = "{{ vars.docs_kit }}"

[task_config]
includes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]
```

(init keeps `includes` on one line — repair logic matches that form.)

`mise run docs:refresh|docs:build|docs:check` then behaves identically in
every consumer repo, running in the consumer's root. `docs-kit init` itself is
shared from this file too. Task bodies prefer a `docs-kit` binary on `PATH`,
else run the clone's source through `uv run --no-dev --project "$DOCS_KIT"`
(project installs re-validate sources by mtime, so a `git pull` in the clone
is live on the very next `mise run` — bare `uvx --from <path>` would cache
stale wheels and must not be used).

`docs:serve` resolves its own listening port: it prefers **8010**, else the
first port nobody LISTENs on within 8000–8999 — via
`shared/scripts/lease-port`, plain POSIX `sh` + `lsof`, stdout is **only**
the port (env knobs `FREE_PORT_MIN` / `FREE_PORT_MAX`, defaults `8000` /
`8999`) — and `DOCS_PORT` pins the port **verbatim**. There is no standalone
port task; if another launcher needs one, call the script directly:
`PORT="$(sh "$DOCS_KIT/shared/scripts/lease-port" 8080)"`. CI only runs
`docs:check`, so runners never touch the port machinery.

Because the tasks come from the clone, **you cannot break them by editing a
consumer repo** — and updating `shared/mise/docs.toml` updates all repos at
once, no per-repo sync. A hand-deleted integration block is repaired with the
same `docs-kit init`.

## Installation — three ways

No PyPI (deliberate). Everything comes from the private repo
`ldelarue/docs-kit` — via SSH key or HTTPS after `gh auth setup-git`.

### 1st — `uv add` from GitHub (git tag pins, no clone)

The `docs-kit` CLI is stdlib-only pure file I/O, installable straight from
the repo. **Git tags are the first-class pins** — that is the registry flow,
since GitHub offers no pip index over artifact storage:

```bash
# pinned to a git tag (recommended — CI reproduces byte-for-byte):
uv add "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@vX.Y.Z"
# or float on the default branch:
uv add "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git"
# one-shot, no project dependency:
uvx --from "docs-kit @ git+ssh://git@github.com/ldelarue/docs-kit.git@vX.Y.Z" docs-kit --version
```

Every release also ships the wheel + sdist as **GitHub Release assets**:

```bash
gh release download vX.Y.Z --pattern '*' --repo ldelarue/docs-kit
uv add ./docs_kit-*-py3-none-any.whl
```

Upgrade = change the `@vX.Y.Z` suffix and `uv lock --upgrade-package docs-kit`
(or re-download the wheel).

This mode ships the CLI only — wheels carry no `shared/` files, so skip the
integration block and drive
`uv run docs-kit init --docs-kit /path/to/checkout` / `refresh` / `check`
directly. The `docs:*` mise tasks live with the clone (2nd).

### 2nd — local clone (default model: full `docs:*` mise tasks)

The `docs:*` tasks are just pointers into your clone (section above) —
**the clone IS the installed version**, and `git pull` is the deliberate,
human reviewable upgrade.

```bash
# 0. once per machine — clone where you like (this checkout is exactly that):
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/me/docs-kit

# 1. per consumer repo (one command writes everything, incl. the clone path):
cd ~/Dev/my-new-api
mise run openapi                                   # produce openapi.json first
uv run --no-dev --project ~/Dev/me/docs-kit docs-kit init
mise run docs:refresh && mise run docs:build

# 2. upgrade only when you decide — nothing auto-updates:
cd ~/Dev/me/docs-kit && git pull                   # or: git checkout vX.Y.Z
cd ~/Dev/my-new-api && mise run docs:refresh && git diff docs/
```

The clone path is the only machine-specific value in a consumer
`.mise.toml`. Per-machine override — never committed — via
`mise.local.toml` (add it to `.gitignore`):

```toml
[vars]
docs_kit = "/other/machine/docs-kit"
```

`docs-kit init` records its own checkout (`--docs-kit` overrides); the value
must be **absolute** — mise's `includes` templates do not expand `~`.

Optional: `uv tool install ~/Dev/me/docs-kit` puts `docs-kit` on `PATH`; the
tasks' `command -v` branches start using it automatically (re-run it after
each pull, or skip it entirely).

Clone **consumers in CI** check the kit out **tag-pinned** too: the
scaffolded `.github/workflows/docs.yml` contains that step (`ref: vX.Y.Z` in
both jobs) — one-time setup is a read-only `DOCS_KIT_PAT` secret per consumer
repo; bump both `ref:` values at each docs-kit release.

### 3rd — build it yourself and use it locally

```bash
cd ~/Dev/me/docs-kit
mise run build         # dist/docs_kit-<ver>-py3-none-any.whl + .tar.gz
mise run install-local # build + uv tool install --force → docs-kit on PATH

# or use the wheel directly, without touching PATH:
uv add /absolute/path/to/docs-kit/dist/docs_kit-*-py3-none-any.whl   # a consumer uv project
uv run --no-project --with dist/docs_kit-*-py3-none-any.whl docs-kit --version
```

Same story in CI without cloning: the `docs-kit-dist` workflow artifact
(`gh run download docs-kit-dist`) or the Release assets.

## CI

- **This repo:** `ci.yml` runs pytest + the lease-port self-tests on every PR
  and on `main`, and uploads `uv build` wheels to a `docs-kit-dist` artifact;
  `release.yml` is the manual release-please dispatch; `publish.yml` attaches
  the built wheels to each GitHub Release.
- **Consumer repos:** `docs-kit init` scaffolds `.github/workflows/docs.yml`;
  its `docs:check` job (kit checkout **pinned by `ref:` tag**) guards docs
  staleness on PRs, the deploy job builds `site/` on `main`. A git hook just
  calls `mise run docs:check`.

## Releasing a version (maintainer)

1. Commit with conventional prefixes: `feat:` → minor, `fix:` → patch,
   `!`/`BREAKING CHANGE` → minor too while pre-1.0 (`docs:`/`chore:` alone
   release nothing).
2. GitHub Actions → Release → **Run workflow** (nothing is automatic): opens /
   updates the release PR bumping `pyproject.toml`, `__version__` and the
   release-please manifest together.
3. Merge it → tag `vX.Y.Z` + GitHub Release; `publish.yml` attaches the
   wheels; bump the consumers' `ref:` / `@vX.Y.Z` pins to the tag.

## Development

```bash
mise install        # python + uv + shellcheck from .mise.toml
mise run test       # uv run pytest
mise run test-scripts  # shellcheck + lease-port scenarios
mise run build / install-local  # see Installation, 3rd way
```

Tests (`tests/`) run the commands against the two real API specs and assert:
byte-identical endpoints pages from both (modulo `info.title` prose),
byte-stable double runs, drift detection, and init idempotence guarantees.
The fixtures are copies of `golang-api-playground/openapi.json` and
`python-api-playground/openapi.json` (semantically equal, byte-different).
