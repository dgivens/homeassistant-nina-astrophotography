"""The model contract's own logic — the switch channel's binary rule."""

from nina_astrophotography.api.models import SwitchChannelModel
import pytest


@pytest.mark.parametrize(
    ("minimum", "maximum", "step_size", "binary"),
    [
        # §5.3.5: Max − Min == StepSize means the channel goes on the switch platform.
        (0.0, 1.0, 1.0, True),
        (0.0, 100.0, 1.0, False),
        # `ReadonlySwitches` carry only Id/Name/Description/Value — no range to test.
        (None, 1.0, 1.0, False),
        (0.0, None, 1.0, False),
        (0.0, 1.0, None, False),
    ],
)
def test_a_switch_channel_is_binary_when_its_range_is_one_step(
    minimum: float | None, maximum: float | None, step_size: float | None, binary: bool
) -> None:
    channel = SwitchChannelModel(
        index=0,
        name="Outlet 1",
        description="",
        value=1.0,
        minimum=minimum,
        maximum=maximum,
        step_size=step_size,
        writable=True,
    )
    assert channel.binary is binary
