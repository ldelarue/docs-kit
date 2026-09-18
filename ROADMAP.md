# docs-kit roadmap — from local path to private-Git install (PyPI not required)

docs-kit will **not** be published to PyPI (not allowed). It is perfectly
usable from a **private Git repository with tags**, installed by mise. This
roadmap turns the current local-path bootstrap into that steady state.
Each phase is independently shippable; only 1–2 are strictly required.

Current state (Phase 0, done): each consuming API repo has the
`docs:init/refresh/build/check` mise tasks, with `[env] DOCS_KIT = <local
checkout>` and tasks that fall back to `uv run --no-dev --project "$DOCS_KIT"`.

---

## Phase 1 — Host docs-kit on private Git

Prereq: `gh` CLI authed as `ldelarue` (or use the web UI).

```bash
cd ~/Dev/me/docs-kit
gh repo create ldelarue/docs-kit --private --source=. --push --remote=origin
# or, with ssh instead of https:
#   git remote add origin git@github.com:ldelarue/docs-kit.git
#   git push -u origin main && git push origin --tags
```

Acceptance (must print the tags):

```bash
git ls-remote --tags origin
```

Consequence check from a clean checkout elsewhere (optional but recommended):

```bash
gh repo clone ldelarue/docs-kit /tmp/dk-check -- --depth 1
(cd /tmp/dk-check && uv run --no-dev --python 3.12 docs-kit --version)
```

Git auth for private HTTPS: with `gh` installed, `git` inherits its
credential helper automatically (`gh auth setup-git`). SSH keys work too.

## Phase 2 — Switch a consumer repo to the installed tool (one repo, then the other)

mise's PyPI backend supports **git-tag sources** (verified at
mise.jdx.dev/dev-tools/backends/pipx.html: `pypi:git+https://…`, tags via the
version). Local *paths* are **not** a supported source, hence this phase.

1. In a scratch dir, let mise generate the exact tool key and inspect it
   (do NOT hand-write it — copy what mise writes into `.mise-config`):

   ```bash
   mkdir -p /tmp/dk-pin && cd /tmp/dk-pin
   mise use 'pypi:git+https://github.com/ldelarue/docs-kit.git@v0.1.1' \
            'pypi:zensical@0.0.62'
   cat .mise.toml          # note the generated key/value shapes
   docs-kit --version      # 0.1.1  -> install works
   ```

   Private-HTTPS auth: `git` uses the `gh` credential helper; if mise runs
   before `gh` auth is available, use the `git@github.com:ldelarue/docs-kit.git`
   (ssh) form.

2. In the consumer repo edit `.mise.toml`: paste the generated key under
   `[tools]`, delete the `[env] DOCS_KIT = "..."` line, and simplify the task
   bodies back to bare `docs-kit`/`zensical` calls (the `command -v` branches
   then always take the installed-binary path — deleting the branches is
   optional, not required).

3. Acceptance:

   ```bash
   cd ~/Dev/me/golang-api-playground
   mise install && command -v docs-kit && command -v zensical
   mise run docs:check          # exit 0, no uv-run fallback used
   ```

   Repeat for `python-api-playground`.

4. CI for private kit sources: a workflow on a private repo can `mise install`
   the git-sourced tools **if the runner can read them**. Add to both jobs (a
   ready-made comment block is already in `.github/workflows/docs.yml`):

   ```yaml
   - uses: actions/checkout@v7
     with:
       repository: ldelarue/docs-kit   # private
       path: .docs-kit
       token: ${{ secrets.DOCS_KIT_PAT }}   # fine-grained PAT, contents:read
   env:
     DOCS_KIT: ${{ github.workspace }}/.docs-kit   # uv-run fallback works
   ```

   Alternative: install via mise in CI by exposing the PAT to git
   (`git config --global url.…insteadOf`), then skip the checkout. Either is
   fine; the checkout + fallback is the least clever and the easiest to
   debug. Create the `DOCS_KIT_PAT` secret in both consumer repos.

## Phase 3 — Day-to-day: manual updates (the permanent workflow, no registry)

Provider side — release vX.Y.Z from `~/Dev/me/docs-kit`:

```bash
cd ~/Dev/me/docs-kit
# 1. bump the version in BOTH files:
#    pyproject.toml [project] version  and  src/docs_kit/__init__.py
# 2. uv run pytest                      (must be green)
git commit -am "release: vX.Y.Z" && git tag vX.Y.Z
git push && git push --follow-tags
```

Consumer side — upgrade or downgrade docs-kit (this is the entire update
model; one line, reviewable as a diff):

```bash
cd ~/Dev/me/golang-api-playground
$EDITOR .mise.toml            # change the docs-kit @v tag line (one edit)
mise install                  # installs the new tag
mise run docs:refresh         # regenerate pages with the new kit
git diff docs/                # see exactly what the upgrade changed
mise run docs:check && git commit -am "deps: docs-kit vX.Y.(Z-1) -> vX.Y.Z"
```

Rollback = change the tag back, `mise install`, refresh. There is no cache
staleness with tagged git sources: a tag is immutable; the only mutable
"latest" pins belong to the old Phase-0 local path (already documented
stale-wheel trap applies to path sources only — git tags are content-hashed).

Recommended hygiene: refresh docs-kit at most when you want to; tags are
pins. Optionally add a scheduled CI job that opens a PR running the consumer
`mise run docs:check` against the newest tag, so upgrades arrive deliberately.

## Phase 4 — Optional polish (after Phases 1–3)

- Install a git hook (`lefthook`/pre-commit) calling `mise run docs:check`.
- Dogfood: migrate docs-playground itself onto docs-kit; publish playground
  style guides from the kit docs.
- Kit convenience: `mise run release vX.Y.Z` task automating Phase-3 provider
  side (bump both files + test + tag + push), `bump-my-version` if manual
  edits annoy.
- If the PyPI ban is ever lifted: switch consumers to
  `"pypi:docs-kit" = "X.Y.Z"` (registry source) via a one-line `.mise.toml`
  edit each; nothing else in the workflow changes — which is exactly why the
  ban stops being a blocker.

## Non-goals

- Publishing to PyPI (explicitly disallowed for now — see Phase 4 fallback).
- Vendoring/copying the kit into consumer repos (duplicated code, drift).
- git submodules (CI/contributor friction, and mise has no lock against a
  submodule path either).
