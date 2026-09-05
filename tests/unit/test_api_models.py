"""models.py distinguishes 'never seen' from 'present but disconnected'."""
import pytest

from nina_astrophotography.api.models import (
    DeviceMeta,
    EquipmentSnapshot,
    SwitchChannelModel,
    WeatherModel,
)


def test_absent_device_is_none_and_disconnected_device_is_a_model() -> None:
    """§5.2.2 and §7.3 both need this distinction from one snapshot."""
    snapshot = EquipmentSnapshot(
        camera=None,
        mount=None, focuser=None, filter_wheel=None, guider=None, rotator=None,
        dome=None, flat_device=None,
        weather=WeatherModel(connected=False, meta=DeviceMeta(None, None, None, None, None),
                             channels={}),
        safety_monitor=None, switch_device=None,
    )
    assert snapshot.camera is None                 # never seen
    assert snapshot.weather is not None            # seen, currently down
    assert snapshot.weather.connected is False


def test_a_switch_channel_is_binary_when_its_range_is_one_step() -> None:
    """§5.3.5: Max − Min == StepSize means the channel goes on the switch platform."""
    outlet = SwitchChannelModel(index=0, name="Outlet 1", description="", value=1.0,
                                minimum=0.0, maximum=1.0, step_size=1.0, writable=True)
    dew = SwitchChannelModel(index=1, name="Dew A", description="", value=40.0,
                             minimum=0.0, maximum=100.0, step_size=1.0, writable=True)
    assert outlet.binary is True
    assert dew.binary is False


@pytest.mark.parametrize(
    ("minimum", "maximum", "step_size"),
    [(None, 1.0, 1.0), (0.0, None, 1.0), (0.0, 1.0, None)],
)
def test_a_channel_with_no_range_is_not_binary(
    minimum: float | None, maximum: float | None, step_size: float | None
) -> None:
    """`ReadonlySwitches` carry only Id/Name/Description/Value — no range to test."""
    channel = SwitchChannelModel(index=2, name="Voltage", description="", value=12.1,
                                 minimum=minimum, maximum=maximum, step_size=step_size,
                                 writable=False)
    assert channel.binary is False
