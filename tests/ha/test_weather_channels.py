"""Weather channels: first-sight creation at the channel granularity (§5.2.2).

The two sources the corpus holds are disjoint in both directions — the physical
station (device-09) reports SkyBrightness and SkyTemperature but not
CloudCover; OpenMeteo (device-12) the reverse — which is what makes the
`unavailable`-versus-`unknown` distinction observable at all.
"""
import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import ATTR_RESTORED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import DOMAIN

CLOUD_COVER = "sensor.n_i_n_a_weather_cloud_cover"
SKY_BRIGHTNESS = "sensor.n_i_n_a_weather_sky_brightness"
SKY_TEMPERATURE = "sensor.n_i_n_a_weather_sky_temperature"
WEATHER_SOURCE = "sensor.n_i_n_a_weather_source"


def _registered(registry, entry: MockConfigEntry, suffix: str) -> str | None:
    return registry.async_get_entity_id(
        SENSOR_DOMAIN, DOMAIN, f"{entry.entry_id}_{suffix}"
    )


async def _reload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
async def cold_entry(hass: HomeAssistant, config_entry: MockConfigEntry, rig):
    """The entry set up with every device down, which is the cold start: no
    weather reading has ever arrived, so no channel exists yet."""
    rig.goto("equipment_disconnected")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def test_a_channel_appears_on_its_first_non_nan_reading(
    hass: HomeAssistant, cold_entry: MockConfigEntry, rig
) -> None:
    """Configuring in daylight, or before the station connects, yields no
    weather entities until the first reading lands."""
    assert hass.states.get(SKY_BRIGHTNESS) is None
    rig.goto("imaging")
    await cold_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(SKY_BRIGHTNESS) is not None


async def test_a_channel_no_source_has_ever_reported_is_not_registered(
    loaded_entry: MockConfigEntry, entity_registry
) -> None:
    """SkyQuality reads "NaN" on both captured sources. An entity at `unknown`
    forever is worse than no entity: it claims a reading is merely missing."""
    assert _registered(entity_registry, loaded_entry, "weather_sky_quality") is None


@pytest.mark.parametrize(
    "suffix",
    ["weather_dew_point", "weather_humidity", "weather_pressure",
     "weather_rain_rate", "weather_sky_brightness", "weather_sky_temperature",
     "weather_temperature", "weather_wind_direction", "weather_wind_gust",
     "weather_wind_speed", "weather_name"],
)
async def test_a_surviving_weather_sensor_keeps_its_1_4_5_unique_id(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    """`weather_name` is `sensor.weather_source`: same value, same purpose."""
    assert _registered(entity_registry, loaded_entry, suffix) is not None


async def test_a_channel_the_active_source_cannot_provide_is_unavailable(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    """Accumulating the union of both sources' channels would leave this one at
    `unknown` forever, which is a lie: OpenMeteo CANNOT report it."""
    await advance("weather_openmeteo")
    assert hass.states.get(SKY_BRIGHTNESS).state == "unavailable"
    assert hass.states.get(CLOUD_COVER).state != "unavailable"


@pytest.mark.synthetic
async def test_a_channel_its_own_source_reads_nan_for_stays_available(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    """The rule applies only where absence is a permanent driver property. The
    station that established SkyBrightness reading "NaN" for one poll is a
    missing reading, not a source that cannot report it."""
    await advance("weather_station_channel_nan")
    assert hass.states.get(SKY_BRIGHTNESS).state == "unknown"


async def test_the_unique_id_does_not_change_with_the_source(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance, entity_registry
) -> None:
    """Keying unique_id on DeviceId would change entity ids on a source swap,
    breaking automations permanently to avoid a rare event."""
    before = entity_registry.async_get(SKY_TEMPERATURE).unique_id
    await advance("weather_openmeteo")
    assert entity_registry.async_get(SKY_TEMPERATURE).unique_id == before


async def test_the_active_weather_source_is_inspectable(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    await advance("weather_openmeteo")
    assert hass.states.get(WEATHER_SOURCE).state == "OpenMeteo"


async def test_a_channel_the_active_source_cannot_feed_survives_a_restart(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    """§1.2's abort criterion. `async_setup_entry` runs before any data
    arrives, and OpenMeteo never reports SkyBrightness — so nothing the poll
    can say brings the channel back, and without the entity registry every
    weather entity would sit `unavailable` from every Home Assistant restart
    until its source next reported.

    `restored` is the assertion, not the state's presence: Home Assistant
    writes an `unavailable` placeholder for every registry row no live entity
    claims, so a channel that was never re-created still answers
    `hass.states.get`.
    """
    await advance("weather_openmeteo")
    await _reload(hass, loaded_entry)
    assert ATTR_RESTORED not in hass.states.get(SKY_BRIGHTNESS).attributes
    assert hass.states.get(SKY_BRIGHTNESS).state == "unavailable"


@pytest.mark.synthetic
async def test_the_establishing_source_survives_a_restart(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    """Which source established a channel is what separates `unavailable` from
    `unknown`, so it is persisted per entity through the registry's options and
    read back at setup. Without it a recovered channel cannot tell a source
    that will never report it from one that is momentarily quiet."""
    await advance("weather_openmeteo")
    await _reload(hass, loaded_entry)
    await advance("weather_station_channel_nan")
    assert hass.states.get(SKY_BRIGHTNESS).state == "unknown"
