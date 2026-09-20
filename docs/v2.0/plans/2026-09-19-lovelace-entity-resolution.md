# Lovelace card entity resolution (post-2.0)

Raised while scoping issue #71 (GUI config editors for the six Lovelace
cards). Every card reads its metrics by templating one `prefix` string onto a
hardcoded entity-id suffix. This plan replaces that with registry resolution on
`nina-observatory-card` first; the other five cards and #71's actual GUI editors
are follow-ups, not in this plan.

Revised after architectural and simplification review. The two design decisions
those reviews left open are settled in **Decisions** at the foot of this
document; the reasoning is recorded there rather than inline.

## Problem

`${prefix}_mount_right_ascension`-style templating works when every child
device's registry name is `f"{instance_name} {KINDS[kind]}"` (`device.py:184`),
so under `has_entity_name` every entity in one config entry inherits the same
leading slug.

**This already fails in a way we ship a manual workaround for.** `README.md`'s
troubleshooting table carries the row *"One device's entities carry a different
prefix than the rest, and its card readings are blank"*: Home Assistant reads
area membership when an entity is **first created**, so placing the hub in an
area after some equipment has connected leaves the already-created devices
unprefixed while later arrivals pick the area up. The card assumes one prefix
per rig, so the mismatched device reads blank, and the documented fix is for the
user to reset that device's entity ids by hand, entity by entity.

That is the case to design for. A user renaming a device or entity through the
UI breaks the card the same way, but it is the hypothetical one — the area-order
bug happens without anyone doing anything unusual, and it is already in the
troubleshooting table. Both are invisible failures: raw string concatenation
with no indirection, so the affected section silently reads `—` with no error.

Risk scales with device count, which is why `nina-observatory-card` (camera,
mount, focuser, filter wheel, guider, dome) goes first.

## Confirmed against the code

- Every `sensor`/`binary_sensor`/`number`/`select`/`switch` descriptor sets
  `translation_key` equal to its `key`, verified by AST over all nine platform
  modules. Exactly one static descriptor lacks one: the guider switch
  (`switch.py:171`). No within-domain duplicates anywhere.
- The hub is identifiable from the browser. `device_identifiers`
  (`device.py:137-140`) gives the hub `{(DOMAIN, entry_id)}` and each child
  `{(DOMAIN, f"{entry_id}_{kind}")}`, and only children set `via_device_id`
  (`device.py:186`). So a hub is *a device carrying a `nina_astrophotography`
  identifier with no `via_device_id`* — which is what makes zero-config
  discovery possible (Decision 1).
- `translation_key` is not globally unique across domains, and there are
  **two** collisions, not one: `focuser_position` (`sensor.py:560` /
  `number.py:129`, deliberate per §5.2.3) and `livestack` (`switch.py:205` /
  `image.py:89`). Keying the map on `"<domain>.<translation_key>"` handles both;
  the domain is recoverable from `entity.entity_id.split(".")[0]`.
- No better client-side key exists. Core's entity-registry display payload
  deliberately carries no `unique_id` — only the registry row id — so
  "resolve by `unique_id`" is not available to a card at all.

### The JS property names — confirmed

This was the one open question the design rested on: core sends the *compact*
display payload (`tk`, `di`, `ei`) and expands it inside
`home-assistant/frontend`, which is not in this repo, so the long names this
design reads were unverified. Settled against that repo rather than devtools:

- `src/state/connection-mixin.ts` builds `hass.entities` keyed by `entity.ei`
  with `entity_id`, `device_id: entity.di` and `translation_key: entity.tk`
  spelled out — so all three names exist at runtime, not just in the type.
- `src/data/entity/entity_registry.ts` declares `EntityRegistryDisplayEntry`
  with `translation_key?: string` and `device_id?: string`.
- `hass.devices` is keyed by `device.id` and holds the **whole**
  `DeviceRegistryEntry` (`src/data/device/device_registry.ts`), including
  `identifiers: [string, string][]` and `via_device_id: string | null`.

The same file also settles the memoization question in the design's favour, and
more strongly than assumed: both subscriptions run their fresh object through
`preserveUnchangedRecord(..., deepEqual)` and call `_updateHass` only when the
result differs by identity. So `hass.entities !== this._resolvedFrom` really
does mean "the registry changed", not "a state ticked".

Note the files moved — they are under `src/data/entity/` and `src/data/device/`
now, not `src/data/`, which is worth knowing before re-checking any of this.

## Three things that break a naive implementation

### 1. `translation_key` is not the entity-id suffix

This is the most load-bearing fact in the document and the easiest to get
wrong. The entity-id suffix is `slugify(device_name) + "_" + slugify(entity_name)`.
`translation_key` is **neither of those**. They agree only when the key happens
to spell out `<kind>_<name>`, which most keys do by convention —
`camera_temperature` on device "N.I.N.A. Camera" with name "Temperature".

In this card, two of 31 lookups diverge:

| lookup | `translation_key` | entity-id suffix |
|---|---|---|
| guider dec RMS | `guider_rms_dec` (`sensor.py`) | `guider_rms_declination` |
| filter wheel select | `filter` (`select.py:113`) | `filter_wheel_filter` |

`select.filter` is the one the first draft of this plan missed. Its device name
supplies "Filter Wheel" and `translations/en.json` names the entity "Filter", so
the id is `select.n_i_n_a_filter_wheel_filter` (`snapshots/entity_ids.txt:32`)
while the map key is `select.filter`. Miss it and the filter-wheel reads
(`nina-observatory-card.js:322` and `:346`) silently stay on the prefix path —
exactly the failure this plan exists to remove, and nothing reports it.

**The follow-up cards are much worse, not "the same treatment".** Of 76
templated lookups across all six cards, **27** need a hand-written suffix:

| card | lookups | key ≠ suffix |
|---|---|---|
| `nina-observatory-card` | 31 | 2 |
| `nina-autofocus-card` | 12 | 10 (`focuser_autofocus_*` ← `autofocus_*`) |
| `nina-weather-card` | 16 | 14 (`weather_*` ← bare channel keys, `sensor.py:876-889`) |

Size the follow-ups accordingly.

### 2. Not every entity has a `translation_key`

The guider on/off switch (`switch.py:170-178`) sets `name=None` on purpose (the
guider device's one function, so it takes the device's own name) and has no
`translation_key`. The resolver never populates an entry for it, so the
per-lookup prefix fallback applies automatically. It stays as rename-fragile as
today — not a regression, just not fixed here. Adding
`translation_key="guider"` is listed under out of scope.

The same is true by construction of the N.I.N.A. switch-device channel entities,
which carry driver-supplied names.

### 3. Disabled entities are absent from `hass.entities` entirely

Core filters `disabled_by is None` when building the display payload. Three of
this card's reads ship disabled and therefore can **never** resolve, whatever
this plan does: `binary_sensor.dome_at_park` (`binary_sensor.py:254`),
`sensor.dome_shutter_status` (`sensor.py:816`) and `sensor.sequence_progress`
(`sensor.py:799`). They stay permanently on the prefix path.

For `sequence_progress` that is harmless — it is disabled because no captured
rig has ever produced a value. For the two dome reads it is issue **#93**: the
card probes dome presence on a disabled entity, so the dome section never
renders for a dome owner. Resolution cannot fix that; probing *device* presence
instead of entity presence can, and this plan's registry walk is what would make
that possible. Out of scope here, tracked in #93.

## Design

### The resolver

**New file:** `custom_components/nina_astrophotography/www/nina-entity-resolver.js`

Resolution is the default, not opt-in: the card finds its own hub, and
`device_id` is only consulted to disambiguate two or more rigs (Decision 1).

```js
const DOMAIN = "nina_astrophotography";

// A hub carries a `nina_astrophotography` identifier and, unlike every child
// device, no `via_device_id` (device.py:137-140,186).
function hubs(devices) {
  return Object.values(devices).filter(
    (device) =>
      !device.via_device_id &&
      device.identifiers?.some(([domain]) => domain === DOMAIN),
  );
}

export function resolveEntities(hass, configuredDeviceId) {
  const map = {};
  const devices = hass?.devices;
  if (!devices) return map;

  // One rig needs no configuration. Two or more are ambiguous, so fall back to
  // the configured device — which may name the hub or any one piece of its
  // equipment, since a child names its hub in `via_device_id`.
  const found = hubs(devices);
  const configured = configuredDeviceId && devices[configuredDeviceId];
  const hubId =
    found.length === 1
      ? found[0].id
      : configured && (configured.via_device_id ?? configured.id);
  if (!hubId) return map;

  const rig = new Set([hubId]);
  for (const device of Object.values(devices)) {
    if (device.via_device_id === hubId) rig.add(device.id);
  }

  for (const entity of Object.values(hass.entities ?? {})) {
    if (!entity.translation_key || !rig.has(entity.device_id)) continue;
    const domain = entity.entity_id.split(".")[0];
    map[`${domain}.${entity.translation_key}`] = entity.entity_id;
  }
  return map;
}
```

Returning `{}` rather than `null` on every failure path keeps the caller free of
null handling.

### Card changes (`nina-observatory-card.js` only, this pass)

`prefix` remains, as the per-lookup fallback whenever a
`"<domain>.<translation_key>"` is not in the resolved map — the guider switch,
the three disabled entities, a transient registry miss, and any install whose
rig the resolver cannot identify. It is no longer the primary mechanism.

`device_id` keeps its existing job of targeting actions and additionally
disambiguates rigs for resolution. It stays optional.

Add an `_eid` method. The third parameter is named `slug`, not `legacySuffix`:
the prefix path is the live path for several lookups, not a deprecated one, and
"slug" matches the vocabulary already in the file (`:8`).

```js
  // Entity ids come from the registry: `translation_key` is the only handle
  // that survives a user renaming a device or an entity, or Home Assistant
  // generating an id under a different area (README troubleshooting). It is
  // unique only per domain — the focuser position exists as both a sensor and
  // a number. The prefix path is the fallback: an entity with no translation
  // key (the guider switch), one that ships disabled and so is absent from
  // `hass.entities` (the dome reads, #93), or a rig the resolver cannot
  // identify. `slug` is the entity-id suffix, which is the device name plus
  // the entity name and so is not always the key: `select.filter` lives on the
  // Filter Wheel device, and `guider_rms_dec` is named "RMS declination".
  _eid(domain, key, slug = key) {
    return this._resolved[`${domain}.${key}`] ?? `${domain}.${this._prefix}_${slug}`;
  }
```

The two calls that need an explicit slug:

```js
this._eid("sensor", "guider_rms_dec", "guider_rms_declination")
this._eid("select", "filter", "filter_wheel_filter")
```

**No restructuring of `_render()`.** The card already funnels every entity read
into a named local at `:317-371` and the render body (`:382-532`) touches only
those locals, never an entity id. So each read is a one-line change in place:

```js
const mntRa = numState(h, this._eid("sensor", "mount_right_ascension"), 4);
```

One micro-fix to fold in: the meridian-flip id is templated twice in adjacent
lines today (`:355`, `:357`). Hoist it rather than calling `_eid` twice.

### Memoization

One memo key, invalidated where the config actually changes, rather than three
fields re-deriving `device_id` on every `hass` set:

```js
  setConfig(config) {
    this._config = config || {};
    this._prefix = this._config.prefix || DEFAULT_PREFIX;
    // A new config may name a different rig: make the next `set hass` re-resolve.
    this._resolved = {};
    this._resolvedFrom = null;
  }

  set hass(hass) {
    this._hass = hass;
    // The frontend keeps `hass.entities` referentially stable until the
    // registry itself changes, so this walks the registry on a rename, not on
    // every state tick.
    if (hass.entities !== this._resolvedFrom) {
      this._resolvedFrom = hass.entities;
      this._resolved = resolveEntities(hass, this._config.device_id);
    }
    this._render();
  }
```

`hass.devices` needs no separate memo key: every device change that alters the
map — a child appearing, a device removed, a second rig added, a rename that
also resets entity ids — arrives with an entity-registry change.

`set hass` now reads `this._config`, which it does not today. That is safe:
Lovelace always calls `setConfig` first, and `_render()` already depends on it
through `_prefix`. Do **not** write `this._config?.device_id` — it would imply a
hazard the card does not have.

Note the memo is a nicety, not a necessity: `_render()` re-serializes the whole
card into `innerHTML` and re-binds 11 listeners on every `hass` set
(`:534-535`), which dwarfs an O(entities) walk. That is the reason to keep it at
one key and not let it grow back.

### Shared module mechanics

Verified safe: `frontend.py:79-81` serves the whole `www/` directory
unconditionally, Lovelace-resource registration is card-only
(`frontend.py:28-36,117-122`), and the removal path filters on `CARD_URLS`
(`frontend.py:156-158`) so the module is untouched when the last entry is
uninstalled. A card's `import "./nina-entity-resolver.js"` is an ordinary
same-origin fetch with no registration step.

Three obligations that come with it (Decision 2):

- **`nina-entity-resolver.js` must not be added to `CARD_FILENAMES`.** It is not
  a card, and registering it would load it standalone on every dashboard,
  defeating the allowlist's stated purpose (`frontend.py:26-27`).
- **`tests/ha/test_frontend.py:182`** asserts
  `{*.js in www/} == set(CARD_FILENAMES)` and will fail. Fix it by introducing
  an explicit non-card set, not by widening the allowlist.
- **The "duplicated on purpose" comment is now false in all six cards.** It
  appears verbatim in `nina-observatory-card.js:282-283`,
  `nina-autofocus-card.js:21-22`, `nina-frame-stats-card.js:102-103`,
  `nina-weather-card.js:154-155`, `nina-sky-map-card.js:197-198` and
  `nina-image-panel-card.js:264-265`, and it is a claim about the *set*, so one
  card importing a shared module invalidates it everywhere. Amend all six in
  this PR.

Also worth one line in the module's header: `StaticPathConfig(..., False)`
(`frontend.py:80`) sets no cache headers and the registered URLs carry no
version query, so a card and its module can skew across an upgrade. Same
exposure the cards already have; not a reason to redesign.

## Tests

The first draft said "no JS test harness exists (confirmed)". That is literally
true and materially misleading, and correcting it is the most important change
in this revision.

**`tests/unit/test_cards.py` is the harness.** Its `TEMPLATED` regex (`:39`)
matches `sensor.${prefix}_foo` and is the only automated check that a card does
not name an entity 2.0 never creates — written because a broken card string
shipped for a whole release (`:1-11`). Rewriting all 31 lookups to
`this._eid("sensor", …)` makes that regex match **zero** occurrences in
`nina-observatory-card.js`. The test keeps passing with no coverage at all, on
the file most likely to contain a typo, and every one of the 27 hand-written
slugs across the six cards is silently wrong if mistyped.

**Required before merge.** Extend `test_cards.py` to parse
`_eid("<domain>", "<key>"[, "<slug>"])` and assert, per call:

1. `<key>` is a `translation_key` that exists in that domain's descriptor
   tables; and
2. the effective suffix — argument 3 where present, else argument 2 — is in
   `snapshots/entity_ids.txt`, reusing the existing `_known()` /
   `_entity_suffixes()` helpers.

That is pure Python, roughly 15 lines, needs no JS harness, and is strictly
stronger than the regex it replaces: it pins both halves of the mapping that
§1 above shows are easy to get out of step. If the per-lookup dual path is kept,
this test is not optional — it is the thing that makes the dual path survivable.

It also pins `translation_key` as a contract. `CLAUDE.md`'s stability rule
covers `unique_id` and explicitly permits the rest to move ("only names and
translation keys change"), while this plan makes six card files and every user's
dashboard depend on translation keys. Better that a future PR renaming a key
fails CI than blanks a dashboard.

`test_cards.py` globs `www/*.js` (`:23`), so it will parametrize over
`nina-entity-resolver.js` too. Harmless — the module names no entities — but
expect the new test ids.

**One trap worth knowing before doing the other five cards.** `LITERAL` (`:40`)
matches a quoted or **backticked** `<domain>.<word>`, which makes prose like
``select.filter`` or ``switch.py`` inside a comment fail
`test_no_card_hardcodes_an_entity_id`. That is the guard working as intended —
it cannot tell a comment from code — so write "the select keyed `filter`"
instead. Expect to hit it: explaining a key/suffix divergence naturally wants to
write exactly that pair, and the five remaining cards have 25 more of them.

## Out of scope

- The other five cards (`nina-autofocus-card`, `nina-sky-map-card`,
  `nina-image-panel-card`, `nina-frame-stats-card`, `nina-weather-card`). Same
  mechanism, 3–5× the hand-written slugs — see §1.
- Issue #71's GUI config editors (`getConfigElement`/`ha-form`). Note that
  `nina-observatory-card.js:563-565` returns `nina-observatory-card-editor`, a
  tag defined nowhere in `www/`, so the GUI editor is already broken for this
  card and `device_id` is YAML-only until #71 builds it.
- Issue **#93** — the dome section never rendering. Its proper fix (probe device
  presence, not entity presence) becomes available once this lands.
- Adding `translation_key="guider"` to `switch.py` to close the one remaining
  unresolvable static entity. Verify `name=None` still wins over
  translation-based naming first.

## Documentation to update

- `README.md:665-668` — the card config block documents `prefix` as the
  mechanism and `device_id` as buttons-only. Reverse the emphasis.
- `README.md:705` — "The Lovelace cards need `prefix:`".
- `README.md` troubleshooting — the "different prefix than the rest" row is the
  bug this plan fixes; it should be deleted or reduced to the two-rig case once
  this lands, not left telling users to reset entity ids by hand.
- `docs/2.0-renames.md:438` already records `device_id`'s introduction, and its
  meaning widens here. No entity, action field or blueprint input is renamed, so
  the strict renames obligation is not triggered.
- The card's top-of-file usage comment (`:4-10`) and the `DEFAULT_PREFIX` block
  (`:277-284`) — `prefix` becomes the fallback, and the second paragraph of the
  `DEFAULT_PREFIX` block is the six-file invariant discussed above.

## Gate to the next

In order. 1 and 2 are done; 3–6 need a browser and are what remains.

1. ~~**The devtools check.**~~ Done, and from the frontend source rather than
   devtools — see "The JS property names — confirmed" above.
2. ~~`test_frontend.py` updated for the non-card module; `test_cards.py` `_eid`
   parsing in place; both suites, ruff and pyright green.~~ Done. Landed beyond
   what this section asked for, because each pins a premise the design rests on
   rather than the code it produced:
   - `test_every_registry_lookup_is_one_this_suite_can_read` asserts every
     `_eid` invocation is one the regex above actually matched. Without it a
     lookup built from a variable would be checked by nothing, which is the
     failure mode this whole section exists to prevent — a green suite over
     unread strings.
   - `test_whatever_a_card_imports_is_served_at_that_path` reads the `import`
     specifier out of the card and fetches it. An ES module that 404s takes its
     importer down with it, so this is a blank card, not a missing helper.
   - `test_the_hub_is_the_only_device_without_a_parent` (`tests/ha/test_devices.py`)
     pins the other half of the discovery predicate;
     `test_children_hang_off_the_hub` already pinned the child half.
   All three new `test_cards.py` assertions were mutation-checked (typo in a
   key, typo in a slug, lookup built from a variable) — each fails on its own
   mutation and nothing else does.
3. Manual verification against a live rig or the fake rig, that the card renders
   identically to today in the single-rig default case — which now takes the
   *resolved* path with no config change, so this is the case that matters most.
4. With two rigs' worth of devices present, `device_id` set to a **child**
   device (the camera, say) rather than the hub: confirm resolution still covers
   the whole rig, including the 11 hub-level reads.
5. Confirm the resolved map actually contains the `select.filter` and
   `sensor.guider_rms_dec` entries rather than falling back to prefix — the
   manual check cannot otherwise distinguish them, since a fallback renders
   identically.
6. Rename one child device in the UI and confirm the card keeps working where
   the prefix-only version would have blanked that section.

## Decisions

**1. Zero-config hub discovery, not opt-in `device_id`.** The failure this plan
fixes is already in `README.md`'s troubleshooting table with a manual
workaround, and nobody hitting it will go and find a device id first — so an
opt-in fix would leave the default install broken and the workaround in place.
Discovery costs one `filter` over `hass.devices`, and `device_id` remains the
disambiguator for two or more rigs. This also makes the resolved path the one
almost every install exercises, which is what the gate above now verifies first.

**2. The shared module ships now, with the full cleanup in the same PR.** The
alternative considered was inlining `resolveEntities` into the card and
extracting it when a second card needs it, which would avoid touching
`test_frontend.py` and the six-file comment while the module has one consumer.
Rejected: the module's mechanics are verified safe, extraction later is churn for
its own sake, and the comment amendment is a six-line mechanical edit rather
than something worth deferring. The cost is that the `CARD_FILENAMES`
exclusion, the `test_frontend.py` non-card set and the six-card comment edit all
become obligations of this PR, listed under "Shared module mechanics" above.
