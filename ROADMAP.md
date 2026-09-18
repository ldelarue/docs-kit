# docs-kit roadmap — clone-based consumption (private Git; no PyPI, no pins)

Docs-kit is consumed by **cloning this repository locally and pointing the
API repos' mise tasks at the clone** (`$DOCS_KIT`). It is never installed
from an index, and there are **no version-pinned git URLs in consumer
configs** (deliberate non-goal). Updates happen only when a human runs
`git pull` in the clone. Tags exist for humans who want a fixed point to
review/return to, not for pinning in configs.

Current state (Phase 0, done): the three repos work off the local clone at
`~/Dev/me/docs-kit`; both API repos have the scaffolded docs and the
`docs:init/refresh/build/check` tasks; CI workflows are scaffolded but not
yet effective (kit remote + secret missing).

---

## Phase 1 — Host docs-kit on private Git

Prereq: `gh` CLI authed as `ldelarue` (or create the repo in the web UI).

```bash
cd ~/Dev/me/docs-kit
gh repo create ldelarue/docs-kit --private --source=. --push --remote=origin
# SSH variant instead:
#   git remote add origin git@github.com:ldelarue/docs-kit.git
#   git push -u origin main && git push origin --tags
git ls-remote --tags origin            # acceptance: prints the tags
```

Private HTTPS auth for humans: run `gh auth setup-git` once so `git` (and
anything shelling out to git) reuses the gh credential helper; or use the
`git@github.com:…` form with SSH keys.

## Phase 2 — Point consumers (and CI) at the clone

1. Anywhere docs-kit is used (every dev machine including fresh ones):

   ```bash
   git clone git@github.com:ldelarue/docs-kit.git ~/Dev/me/docs-kit
   ```

   Path is personal preference; only the value recorded in the consumer
   `.mise.toml` must match. On machines where these repos already exist
   (this Mac), the clone already IS `~/Dev/me/docs-kit` — nothing to do.

2. New consumer repo: `mise run openapi` then
   `uv run --no-dev --project ~/Dev/me/docs-kit docs-kit init` (writes
   `[env] DOCS_KIT = <the clone path>` + the four tasks). Existing repos:
   keep the block as-is; only fix `DOCS_KIT` if the clone moved.

3. Acceptance per consumer repo:

   ```bash
   cd ~/Dev/me/golang-api-playground
   mise run docs:refresh && mise run docs:build && mise run docs:check  # exit 0
   ```

4. CI on the consumer repos (one-time per repo):
   - create a fine-grained `DOCS_KIT_PAT` secret (read `contents` on
     `ldelarue/docs-kit`);
   - apply the commented CI recipe at the top of
     `.github/workflows/docs.yml`: a kit checkout step + writing
     `[vars] docs_kit = "$GITHUB_WORKSPACE/.docs-kit"` into
     `mise.local.toml` (the include path must resolve on the runner or the
     docs tasks silently vanish).
   - CI checks the kit repo **at the default branch** (drifts with pushes —
     fine); to freeze CI, add `ref: v0.1.3` to that checkout step. `mise run
     docs:check` on PRs then guards docs staleness, deploy builds `site/` on
     main.

## Phase 3 — Day-to-day workflow (the permanent manual model)

Provider side (release only when content changed; tags are review points):

```bash
cd ~/Dev/me/docs-kit && git pull
# bump [project].version in pyproject.toml AND __version__ in
# src/docs_kit/__init__.py (keep them equal), then:
uv run pytest                                  # must be green
git commit -am "release: vX.Y.Z" && git tag vX.Y.Z
git push && git push --follow-tags
```

Consumer side / any user updating the clone:

```bash
cd ~/Dev/me/docs-kit && git pull               # or git checkout vX.Y.Z
cd ~/Dev/me/golang-api-playground
mise run docs:refresh && git diff docs/        # see exactly what changed
mise run docs:check && git commit -am "docs: regenerated with docs-kit <ref>"
```

- The clone is self-refreshing for `mise run docs:*` (both the task
  definitions in `shared/mise/docs.toml` and the Python sources re-validate
  from the clone on every `mise run`) — no reinstall needed unless you also
  did `uv tool install` (then re-run it, or uninstall; the `command -v`
  branch would freeze the old binary otherwise).
- Rollback = `git checkout <older-tag-or-commit>` in the clone and refresh.
- Never `git pull` blindly inside a CI/docs-refresh assumption of stability:
  CI never has your personal clone anyway (it checks out its own); only the
  default-branch freshness note in Phase 2.4 applies.

## Phase 4 — Optional later improvements

- `uv tool install ~/Dev/me/docs-kit` once per machine if invoking the bare
  `docs-kit` binary is preferred over the tasks' uv-run branch.
- Kit dev automation: a `release` mise task bumping both version fields,
  testing, tagging, pushing (Phase 3 provider side in one command).
- Git hook manager (lefthook/pre-commit) calling `mise run docs:check` on
  commits touching spec/code in each API repo.
- Dogfood phase: migrate `docs-playground` onto docs-kit so the kit can
  dogfood its own pages.
- If a PyPI ban is ever lifted *and wanted*: replace `DOCS_KIT` blocks with
  `"pypi:docs-kit" = "X.Y.Z"` + bare task calls — one `.mise.toml` swap per
  repo, nothing else changes.

## Non-goals (deliberate, revisit only together with the reasons)

- **Publishing to PyPI** (disallowed today; unnecessary with the clone
  model).
- **Version-pinned git tool sources in consumers** (`pypi:git+…@vX` in
  `[tools]`, `mise use …@semver`) — rejected in favor of clone + manual pull
  so upgrading is always a human, reviewable act in one obvious place.
- Vendoring kit sources into consumer repos; git submodules (CI/contributor
  friction and the same staleness questions, without the simple `$DOCS_KIT`
  story).
