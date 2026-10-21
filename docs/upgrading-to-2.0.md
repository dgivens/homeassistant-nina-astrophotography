# Upgrading from 1.4.x to 2.0

Your existing entity ids don't change. Home Assistant identifies entities by
their `unique_id`, so an upgraded install keeps the ids it already has and your
dashboards and automations keep pointing at them. The entities move onto new
per-equipment devices. A fresh install gets different ids;
[`2.0-renames.md`](2.0-renames.md) maps every one.

Home Assistant 2026.9.0 or later is required.

## What to do

1. **Delete the old card resources.** In 1.4.x you copied the card files into
   `/config/www/` and added `/local/nina-*.js` resources by hand. 2.0 registers
   its own. Remove the old resources under **Settings → Dashboards → ⋮ →
   Resources** (the menu entry appears only with *Advanced mode* on in your
   user profile). Deleting the files is optional. If you leave them, the old and
   new versions of each card compete to load, and whichever loads second
   doesn't work. Each card logs `NINA-…-CARD vX.Y.Z` to the browser console;
   if you see `v1.0.0`, an old resource is still loading. Hard-reload the
   dashboard after removing them.
2. **Re-import the blueprints and rebuild their automations.** All five
   blueprints were rewritten with new inputs, and `imaging_stall_alert.yaml`
   is new. The 1.4.x blueprints used entities 2.0 doesn't create, so they did
   nothing after the upgrade anyway.
3. **Update automations that use these actions**, which didn't work in 1.4.5:
   - `camera_capture`: use `duration` instead of `exposure`. `binning` and
     `filter_index` are removed.
   - `sequence_load`: use `sequence_name` instead of `path`.
   - `mount_slew`: use `ra_degrees` and `dec_degrees`, in J2000 degrees. The
     old `ra` was in hours.
4. **Update automations that read event data.** Event fields moved from
   `response` to `data`: `trigger.event.data.response.IsSafe` is now
   `trigger.event.data.data.IsSafe`.
5. **Replace references to removed entities.** These break silently:
   - `binary_sensor.<instance>_sequence_running`: use
     `_sequencer_running` (the sequencer is running, including waits) or
     `_imaging` (frames are being taken). The session shutdown blueprint
     needs `_sequencer_running`; on `_imaging` it would shut down during any
     wait. See the [reference](reference.md#is-the-rig-working).
   - The equipment `*_connected` sensors: a disconnected device's entities
     now become `unavailable`. The safety monitor keeps its
     `_connected` sensor.
   - The gain, offset and binning `number` entities: gain and offset are now
     read-only sensors.
   - `switch.<instance>_flat_panel_light`: use the `light` entity.

   [`2.0-renames.md`](2.0-renames.md) lists every removal.
6. **Delete the leftover entities.** Removed entities stay in the registry as
   `unavailable` until you delete them from **Settings → Devices & Services →
   Entities**.
7. **If you have two rigs,** give each card a `device_id:`. With one rig the
   cards need no configuration.

## Other changes

- Driver name and version moved from entity attributes to the device page.
- The poll interval is capped at 60 seconds. An existing entry with a longer
  interval keeps it until you next save the options.
- `sensor.<instance>_session_integration_time` is now in hours instead of
  minutes, and both it and `sensor.<instance>_session_image_count` changed
  state class. Their long-term statistics start over; the old history isn't
  carried across.

See [`CHANGELOG.md`](../CHANGELOG.md) for the full list.
