# Branches, pull requests and releases

- `main` — the trunk and the shipping line; every PR targets it. Stack PRs
  only when one builds on another's diff (stack #17); independent fixes are
  plain PRs onto `main`.
  **Create one with `gh stack init --base main <bottom> <top>`, then `gh stack
  submit --auto --remote origin`** — `gh pr create --base <branch>` chains the
  bases but GitHub tracks no stack, so a bottom-up merge strands the upper PR on
  a deleted branch. Adopting already-open PRs after the fact is safe and edits
  neither; `--remote` is a flag on `submit`, not on `init`.
  **Extend an existing stack with `gh stack add <branch>` from the stack's
  current top branch** — run from the new branch it answers "is not part of a
  stack"; it adopts an existing branch with its commits and checks it out.
  `init` fails with "already exists in a stack", and `gh stack view` works only
  from a branch inside it (checking one out swaps the working tree).
  `submit --auto` creates each new PR as a **draft titled from the branch
  name**, so `gh pr edit` the real title and body, then `gh pr ready`.
  **Every `gh stack` command needs `GH_REPO=<your fork>` and
  `--remote origin`**: it auto-detects `upstream` and will try to create
  duplicate PRs there. `gh repo set-default` covers `gh pr`, not `gh stack`.
  One branch per task, named for it.
- **PRs are squash-merged.** A mechanical reformat ships as its own PR, and
  its squash SHA goes into `.git-blame-ignore-revs` after it merges. Git never
  sees a squashed branch as merged (`--merged`, `git cherry`), so check the
  PR's state before `git branch -D`.
- **A release** bumps `version` in `manifest.json` and `pyproject.toml` and
  dates its CHANGELOG section, then tags `v<version>` on `main` and publishes
  a GitHub release from it — HACS offers releases, not commits. A beta is
  `v<version>b<N>`, published as a pre-release.

## Quality bar

Target the Home Assistant **Bronze** quality-scale tier, and treat Silver/Gold
rules as guidance rather than gates. The Bronze rules that bind us:

- `config-flow-test-coverage` — **100%** on the config flow, including error
  recovery and the duplicate-entry guard
- `test-before-configure` / `test-before-setup` — validate the connection in the
  config flow; raise `ConfigEntryNotReady` vs `ConfigEntryError` correctly
- `runtime-data` — state lives on `entry.runtime_data`, never
  `hass.data[DOMAIN][entry_id]`
- `common-modules` — the coordinator is `coordinator.py`, the base entity is
  `entity.py`
- `has-entity-name` — entity names derive from their device
- `appropriate-polling`, `entity-unique-id`, `entity-event-setup`

`reauthentication-flow` is **exempt**: the Advanced API has no authentication.
Record exemptions in `quality_scale.yaml` rather than leaving them looking
unimplemented.
