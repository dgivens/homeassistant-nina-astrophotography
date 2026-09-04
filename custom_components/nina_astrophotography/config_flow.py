"""Config flow for N.I.N.A. Astrophotography integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .legacy_api import NinaApiClient, NinaConnectionError
from .const import (
    CONF_API_VERSION,
    CONF_HOST,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    DEFAULT_API_VERSION,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _validate_connection(hass: HomeAssistant, data: dict) -> str | None:
    """Try to connect and return the N.I.N.A. version string or raise."""
    session = async_get_clientsession(hass)
    client = NinaApiClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        api_version=data[CONF_API_VERSION],
        session=session,
    )
    result = await client.get_version()
    # The API returns {"Response": "x.x.x.x", ...}
    return result.get("Response", "unknown")


class NinaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for N.I.N.A. Astrophotography."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                version = await _validate_connection(self.hass, user_input)
            except NinaConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during N.I.N.A. config validation")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"N.I.N.A. {version} @ {user_input[CONF_HOST]}",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="192.168.1.100"): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_API_VERSION, default=DEFAULT_API_VERSION): vol.In(["v2"]),
                vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): vol.All(
                    int, vol.Range(min=5, max=300)
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> NinaOptionsFlow:
        return NinaOptionsFlow(config_entry)


class NinaOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the N.I.N.A. integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): vol.All(int, vol.Range(min=5, max=300)),
                }
            ),
        )
