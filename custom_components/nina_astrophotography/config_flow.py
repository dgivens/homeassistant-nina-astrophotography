"""Config flow for the N.I.N.A. Astrophotography integration."""

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

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
    CONF_OUTAGE_GRACE,
    CONF_PORT,
    CONF_ROLLOVER_HOUR,
    DEFAULT_INSTANCE_NAME,
    DEFAULT_OUTAGE_GRACE,
    DEFAULT_PORT,
    DEFAULT_ROLLOVER_HOUR,
    DOMAIN,
    normalize_host,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        # Stripped first: `vol.Length` alone accepts "   ".
        vol.Required(CONF_INSTANCE_NAME, default=DEFAULT_INSTANCE_NAME): vol.All(
            str, vol.Strip, vol.Length(min=1)
        ),
    }
)


class NinaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for N.I.N.A. Astrophotography."""

    VERSION = 1
    # `async_migrate_entry` brings an earlier minor version up to this one.
    MINOR_VERSION = 3

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = {
                **user_input,
                CONF_HOST: normalize_host(user_input[CONF_HOST]),
            }
            # No unique id: the API reports no stable id of its own, and an
            # address is not one.
            if self._address_in_use(user_input[CONF_HOST], user_input[CONF_PORT]):
                return self.async_abort(reason="already_configured")
            if self._name_in_use(user_input[CONF_INSTANCE_NAME]):
                errors[CONF_INSTANCE_NAME] = "name_in_use"
            else:
                client = NinaClientV2(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    async_get_clientsession(self.hass),
                )
                try:
                    await client.get_versions()
                except NinaConnectionError, NinaUnavailableError, NinaCommandError:
                    # Transient or equipment-level: the address is probably right.
                    errors["base"] = "cannot_connect"
                except NinaEndpointError, NinaRequestError:
                    # A plugin too old, or another service on the port.
                    errors["base"] = "unsupported_api"
                except Exception:
                    _LOGGER.exception(
                        "Unexpected error validating the N.I.N.A. connection"
                    )
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title=user_input[CONF_INSTANCE_NAME], data=user_input
                    )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    def _address_in_use(self, host: str, port: int) -> bool:
        """Whether another entry already reads this host and port.

        Each stored host is normalised here too: a disabled entry is never
        migrated, so one from before 2.0 keeps the host as it was typed.
        """
        return any(
            normalize_host(entry.data[CONF_HOST]) == host
            and entry.data[CONF_PORT] == port
            for entry in self._async_current_entries(include_ignore=False)
        )

    def _name_in_use(self, name: str) -> bool:
        """Whether another entry already has this instance name.

        The title stands in for an entry from before 2.0 that has not been
        migrated yet, as a disabled one never is.
        """
        return any(
            entry.data.get(CONF_INSTANCE_NAME, entry.title) == name
            for entry in self._async_current_entries()
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NinaOptionsFlow:
        """Create the options flow; Home Assistant sets its `config_entry`."""
        return NinaOptionsFlow()


class NinaOptionsFlow(config_entries.OptionsFlowWithReload):
    """Handle options for the N.I.N.A. integration.

    Each option is read once at setup, so a change reloads the entry.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ROLLOVER_HOUR,
                        default=options.get(CONF_ROLLOVER_HOUR, DEFAULT_ROLLOVER_HOUR),
                    ): vol.All(int, vol.Range(min=0, max=23)),
                    vol.Optional(
                        CONF_OUTAGE_GRACE,
                        default=options.get(CONF_OUTAGE_GRACE, DEFAULT_OUTAGE_GRACE),
                    ): vol.All(int, vol.Range(min=0, max=300)),
                }
            ),
        )
