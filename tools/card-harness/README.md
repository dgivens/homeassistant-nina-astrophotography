# Card harness

The six Lovelace cards run in a browser. Neither test suite renders one, so
everything below `setConfig`/`set hass` — the shadow DOM, the canvases, every
branch that decides what to draw — is reached by nothing in CI. This is how you
reach it by hand.

Two tools, answering different questions:

| | Question | Needs |
|---|---|---|
| `ops.mjs` | did this change alter what the card draws? | node |
| `render.html` | does it look right? | a browser |

Neither is a test. The automated version is issue #95.

## The data is not made up

Both read `tests/ha/snapshots/card_states.json`, which
`tests/ha/test_card_states.py` regenerates from the fake rig: captured wire
data, one mapper and one platform table later. It holds the whole `hass` a card
is handed — `states`, plus the `entities` and `devices` registries a card
resolves ids from.

A scenario therefore composes by **subtracting** from a real rig, never by
inventing one. `Rig.override` exists for what the corpus cannot produce, and a
scenario using it says why at the call site.

Regenerate it with the rest of the snapshots, in its own commit:

```bash
uv run --group test-ha pytest tests/ha/test_card_states.py -q   # writes, then fails
```

Three rig states are dumped: `site_configured` (everything up, with an
observing site), `equipment_disconnected` (the drivers down) and `dawn_flats`
(a whole night's session, dumped from inside it). Only the last holds a
session: it is measured against the clock, and the other two are dumped on a
later day than their night, so the image history is all their frames carry. Device ids are
pseudonyms — Home Assistant mints fresh ones per run — and the image entities'
access tokens read `<per run>`.

## Did this change alter what the card draws?

`ops.mjs` runs a card under node against stub DOM and a canvas that logs every
call instead of drawing it, then prints the log. The point is the diff: record
before a refactor and after, and output that has not moved says the change was
one.

```bash
CARD=custom_components/nina_astrophotography/www/nina-sky-map-card.js
git show <before>:$CARD > /tmp/before.js
node tools/card-harness/ops.mjs /tmp/before.js tracking --card=nina-sky-map-card > /tmp/before.txt
node tools/card-harness/ops.mjs $CARD tracking | diff /tmp/before.txt -
```

`--card` names the scenario file, which is the card's name and not the path —
so a copy pulled out of git needs it. `--html` prints the rendered markup too.

Two sources of noise are pinned, or a card would differ from itself: the sky
map twinkles stars with `Math.random()` and pulses the meridian off `Date.now()`.

A log is not a picture. It proves two versions agree, not that either is right.

## Does it look right?

`render.html` lays a card's scenarios out side by side in a real browser —
the only thing here that exercises layout, fonts, `<canvas>` and the shadow DOM
for real.

```bash
python3 -m http.server 8901 --directory .     # from the repo root
open "http://127.0.0.1:8901/tools/card-harness/render.html?card=nina-sky-map-card"
```

Served, not opened as a file: the cards are ES modules that import each other,
and a `file://` origin refuses. `?scenario=` renders one of them alone. The page
title carries the error count, and a scenario that throws shows its stack in
place rather than taking the others down.

## Adding a card

Write `scenarios/<card name>.mjs` exporting `scenarios`, keyed by name:

```js
{
  hass: (dump) => rig(dump, "site_configured").without("site_latitude").build(),
  config: { prefix: "n_i_n_a" },   // optional, straight to setConfig
  draw: (card) => card._drawFrame(),  // optional, see below
}
```

A card paints its canvas on an animation frame, which node never fires, so
`ops.mjs` runs the ones the render queued. `draw` replaces that for a card the
queued frames do not cover, which today is only the sky map: it paints from a
loop started in `connectedCallback`, and nothing here attaches the element. A
hook also *suppresses* the queued frames, so a card that stops queueing one
still draws under its hook and the diff says nothing — prefer no hook.
