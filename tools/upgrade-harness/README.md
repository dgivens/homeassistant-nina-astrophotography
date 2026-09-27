# Upgrade harness

Upgrades a throwaway Home Assistant, in Docker, from one version of the
integration to another, against a real N.I.N.A., and checks the result against
`docs/2.0-renames.md`. Neither test suite can do this: both start from an empty
registry, and an upgrade is about the registry an older version left behind.

```bash
H="uv run python tools/upgrade-harness/harness.py"
$H up --ref origin/main          # 1.4.5, against the simulator rig
$H snapshot before
$H upgrade --ref origin/v2       # swap in 2.0 and restart
$H snapshot after
$H check before after            # exits 1 on any mismatch
$H down
```

Each step needs the network, so run it outside the Bash sandbox.

- **`up`** creates `.run/` (git-ignored), installs the integration from a git
  ref into a fresh `/config`, and starts `ghcr.io/home-assistant/home-assistant`.
  It onboards through Home Assistant's own onboarding API, mints a long-lived
  token, and adds the rig through the config flow. Only the host and port are
  sent, so each version's own defaults fill in the rest of its form.
  - The instance is at <http://127.0.0.1:8124>; log in as `harness` /
    `harness-password` to look around.
  - The rig defaults to the simulator N.I.N.A. (`--host`, `--port`).
  - The image defaults to Home Assistant 2026.9.0 (`--image`).
- **`upgrade`** replaces the integration with another ref's and restarts the
  container. The registry, the entry and the recorder carry over, as they do on
  a real upgrade.
- **`snapshot`** records this integration's entity and device registry rows,
  their states, and its config entries as JSON under `.run/`.
- **`check`** walks every entity the first snapshot holds and requires three
  things:
  - it keeps its entity id;
  - it is left an orphan if the doc says it was removed;
  - it is still backed by a live entity otherwise.

  The doc names most entities in a row of their own. A row's "Why" also names
  its siblings by `unique_id` suffix ("Same for `_frame_last_max_adu`"), and
  those count as sharing the row's fate. A disabled row has no state to judge,
  so it is only listed.

## Only against the simulator

Setting an entry up polls every endpoint the version reads, and 2.0 pushes
nothing to the rig on its own. But the point of a throwaway instance is to try
things in it. Point it at the simulator N.I.N.A., where any command is allowed,
never at the live rig.

## What it has found

- 1.4.5 published `sensor.*_sky_brightness` in `lux`, which Home Assistant does
  not accept for `illuminance`, and 2.0 publishes `lx`. After the upgrade, the
  recorder stops that sensor's long-term statistics until the user fixes the
  unit (CHANGELOG, 2.0.0).
