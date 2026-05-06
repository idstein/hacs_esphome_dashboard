"""Models for ESPHome Dashboard integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiohttp import ClientSession

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import ESPHomeDashboardCoordinator

@dataclass
class ESPHomeDashboardRuntimeData:
    """Runtime data for ESPHome Dashboard integration."""

    coordinator: ESPHomeDashboardCoordinator
    session: ClientSession

ESPHomeDashboardConfigEntry = ConfigEntry[ESPHomeDashboardRuntimeData]
