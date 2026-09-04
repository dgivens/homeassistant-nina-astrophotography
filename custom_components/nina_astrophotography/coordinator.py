"""DataUpdateCoordinator for N.I.N.A. Astrophotography."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .legacy_api import NinaApiClient, NinaApiError, NinaConnectionError

_LOGGER = logging.getLogger(__name__)


class NinaDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls N.I.N.A. API and distributes data to all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: NinaApiClient,
        poll_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="N.I.N.A. Astrophotography",
            update_interval=timedelta(seconds=poll_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.poll_all()
        except NinaConnectionError as exc:
            raise UpdateFailed(f"Cannot reach N.I.N.A.: {exc}") from exc
        except NinaApiError as exc:
            raise UpdateFailed(f"N.I.N.A. API error: {exc}") from exc
