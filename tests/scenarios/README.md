# Rig states

`states.py` names the rig conditions the phase B and C tests advance through;
`fake_rig.py` serves one of them at a time to the real `NinaClientV2`.

## What a state is

A dict of endpoint key → the **full envelope the wire sent**, so the client's
envelope classification, the `"NaN"` rule and the wire→model mapper all run
against captured bytes. An endpoint key is the client's path with its single
query parameter appended where the answer depends on it —
`/image-history?count=true` — because the client passes parameters separately
from the URL. `"*"` matches every path the state does not name.

Every state carries the same endpoints. A path no state serves answers 404 with
EmbedIO's HTML, which the client raises as `NinaEndpointError`: a missing
endpoint fails loud instead of quietly succeeding. Command paths
(`…/set-light`, `…/set-brightness`, `/sequence/start`) are never in a state —
they are recorded on `rig.sent` and answered `Success: true`, because no
command on this API can be confirmed from its own response.

## Using one

```python
async def test_the_light_goes_down_with_the_panel(hass, loaded_entry, advance):
    await advance("equipment_disconnected")
    assert hass.states.get(LIGHT).state == "unavailable"
```

`advance` (in `tests/ha/conftest.py`) moves the rig, refreshes the coordinator
and lets Home Assistant settle. `FakeRig.advance()` is the other one: it walks
an ordered `SEQUENCES` entry step by step.

## Adding one

Build it from captured envelopes — `load_envelope`, `disconnect()`, a slice of
a captured list. Never hand-write a wire document: the published spec is
unreliable about types and the captured corpus is the only record of what the
rig actually sends.

If the corpus cannot show the state, add its name to `AWAITING_CAPTURE` with a
line saying what a capture must contain, and leave the tests that need it to
skip. `advance()` skips them by name. A state must never be faked into
existence to turn a skip green.
