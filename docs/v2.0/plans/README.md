# v2.0 implementation plans

`docs/v2.0-design.md` is the design of record. These are its execution plans,
one per phase of §9, in order. Each is self-contained: an engineer picking one
up needs that file plus the spec, nothing else.

| Plan | Phase | Size | Gate to the next |
|---|---|---|---|
| [`2026-09-04-phase-a-foundation.md`](2026-09-04-phase-a-foundation.md) | A · Foundation | L | §12's phase-A exit criteria |
| [`2026-09-04-phase-b-devices-push-first.md`](2026-09-04-phase-b-devices-push-first.md) | B · Devices + push-first | L | Device registry + tiers proven; renames doc started |
| [`2026-09-04-phase-c-platforms.md`](2026-09-04-phase-c-platforms.md) | C · Platforms | XL | `api.py` deleted; registry snapshot reviewed |
| [`2026-09-04-phase-d-services-docs-release.md`](2026-09-04-phase-d-services-docs-release.md) | D · Services, blueprints, docs, release | L | §12 definition of done |

## Branch model

`fix/api-endpoint-paths` (1.4.5) is **already merged** to `main` (`68c04ca`), so
D-06 is satisfied. Cut `v2` from `main` once, at the start of phase A:

```bash
git checkout main && git pull && git checkout -b v2
```

Every phase is a set of PRs into `v2`. `v2` → `main` and tag `2.0.0` in D2.
There is no `legacy` passthrough: the requirement is that **every PR's tests are
green**, not that the branch boots (§9).

## Abort criterion

Phase C is XL and this integration drives a live observatory. If it stalls, `v2`
is parked and 1.4.x continues to ship; nothing in phases A–B is user-visible
(§1.2).

## Amendment rule

A PR that contradicts `docs/v2.0-design.md` amends it in the same PR and bumps
the rev in its header. That applies to these plans too — if execution proves a
task wrong, fix the plan in the PR that proves it.
