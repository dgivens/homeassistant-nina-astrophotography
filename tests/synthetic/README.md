# Synthetic fixtures

Constructed, not captured. **Authoritative about nothing but our own branches.**
Never add a synthetic file for a subsystem real hardware can produce — a
captured fixture encodes reality, a hand-written one encodes the spec's
mistakes, and the published spec is unreliable about types.

A test that reads one asserts **branch reachability only, never values**, and
carries `@pytest.mark.synthetic`.

| File | Why it cannot be captured |
|---|---|
| `dome_connected.json` | No dome is available and none is in prospect (§5.3.1) |

`dome_connected.json` is a real *disconnected* `/equipment/info` capture with
its `DomeInfo` block flipped: `Connected` true, the identity keys the wire
drops on disconnect put back, `"NaN"` azimuth replaced with a plausible number
and the capability flags turned on. Every other device block is the capture's
own.

Derived states that live in `tests/scenarios/states.py` rather than here — a
disconnected camera, a dimmable switch channel, a read-only gauge — are one
field away from a captured block and are documented at their definition.
