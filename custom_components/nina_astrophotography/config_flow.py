"""Config flow for the N.I.N.A. Astrophotography integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaRequestError,
    NinaUnavailableError,
)
from .api.v2 import NinaClientV2
from .const import (
    CONF_HOST,
    CONF_INSTANCE_NAME,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_ROLLOVER_HOUR,
    DEFAULT_INSTANCE_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_ROLLOVER_HOUR,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_POLL_INTERVAL = vol.All(int, vol.Range(min=5, max=60))

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_INSTANCE_NAME, default=DEFAULT_INSTANCE_NAME): str,
        vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): _POLL_INTERVAL,
    }
)


class NinaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for N.I.N.A. Astrophotography."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            client = NinaClientV2(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                async_get_clientsession(self.hass),
            )
            try:
                await client.get_versions()
            except (NinaConnectionError, NinaUnavailableError, NinaCommandError):
                # Transient or equipment-level: the address is probably right.
                errors["base"] = "cannot_connect"
            except (NinaEndpointError, NinaRequestError):
                # Something answers, but not the Advanced API this expects —
                # a plugin too old, or another service on the port.
                errors["base"] = "unsupported_api"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating the N.I.N.A. connection")
                errors["base"] = "unknown"
            else:
                # Host and port, not a rig-reported id: the API exposes nothing
                # stable, and this is what a second instance must differ in.
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_INSTANCE_NAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NinaOptionsFlow:
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

        options = self._config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): _POLL_INTERVAL,
                    vol.Optional(
                        CONF_ROLLOVER_HOUR,
                        default=options.get(
                            CONF_ROLLOVER_HOUR, DEFAULT_ROLLOVER_HOUR
                        ),
                    ): vol.All(int, vol.Range(min=0, max=23)),
                }
            ),
        )
