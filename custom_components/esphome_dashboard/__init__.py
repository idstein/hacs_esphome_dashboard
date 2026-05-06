"""The ESPHome Dashboard integration."""

from __future__ import annotations

import logging
import aiohttp

from esphome_dashboard_api import ESPHomeDashboardAPI

from homeassistant.helpers import aiohttp_client
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .coordinator import ESPHomeDashboardCoordinator
from .models import ESPHomeDashboardConfigEntry, ESPHomeDashboardRuntimeData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.UPDATE]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True

async def async_setup_entry(
    hass: HomeAssistant, entry: ESPHomeDashboardConfigEntry
) -> bool:
    """Set up ESPHome Dashboard from a config entry."""
    url = entry.data[CONF_URL]
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)

    auth = None
    if username and password:
        auth = aiohttp.BasicAuth(username, password)

    session = aiohttp_client.async_get_clientsession(hass)
    api = ESPHomeDashboardAPI(url, session, auth=auth)

    coordinator = ESPHomeDashboardCoordinator(hass, api, entry)

    await coordinator.async_config_entry_first_refresh()

    # Store both coordinator and session for proper cleanup
    entry.runtime_data = ESPHomeDashboardRuntimeData(
        coordinator=coordinator,
        session=session,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(
    hass: HomeAssistant, entry: ESPHomeDashboardConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
