"""Support for ESPHome Dashboard update entities."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from aioesphomeapi import APIClient, APIConnectionError
from esphome_dashboard_api import ConfiguredDevice
from zeroconf.asyncio import AsyncServiceInfo

from homeassistant.components import zeroconf
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_CONFIGURATION, CONF_URL
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ESPHomeDashboardConfigEntry
from .const import DEFAULT_PORT, DOMAIN, ESPHOME_CHANGELOG_URL
from .coordinator import ESPHomeDashboardCoordinator

if TYPE_CHECKING:
    from homeassistant.components.esphome import RuntimeEntryData

_LOGGER = logging.getLogger(__name__)

# ESPHome mDNS service type for port discovery
ESPHOME_SERVICE_TYPE = "_esphomelib._tcp.local."

# All entities share a DataUpdateCoordinator, so no parallel updates needed
PARALLEL_UPDATES = 0


def _normalize_name(name: str) -> str:
    """Normalize name for comparison."""
    return name.lower().replace(" ", "-").replace("_", "-")


def _find_esphome_device_mac(hass: HomeAssistant, device_name: str) -> str | None:
    """Find MAC address for an ESPHome device by name in device registry."""
    dev_reg = dr.async_get(hass)
    normalized_target = _normalize_name(device_name)

    # Search for device by name
    for device in dev_reg.devices.values():
        if device.name and _normalize_name(device.name) == normalized_target:
            # Check if this device has a MAC connection (from ESPHome integration)
            for conn_type, conn_id in device.connections:
                if conn_type == dr.CONNECTION_NETWORK_MAC:
                    return conn_id
    return None


def _find_esphome_entry_data(
    hass: HomeAssistant, device_name: str
) -> RuntimeEntryData | None:
    """Find RuntimeEntryData for an ESPHome device by name."""
    normalized_target = _normalize_name(device_name)
    for entry in hass.config_entries.async_entries("esphome"):
        if entry.state != ConfigEntryState.LOADED:
            continue
        entry_data: RuntimeEntryData = entry.runtime_data
        if not entry_data.device_info:
            continue
        if _normalize_name(entry_data.device_info.name) == normalized_target:
            return entry_data
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ESPHomeDashboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up ESPHome Dashboard update entities."""
    coordinator: ESPHomeDashboardCoordinator = entry.runtime_data.coordinator

    # Track which devices we've already created entities for
    known_devices: set[str] = set()

    @callback
    def async_add_update_entities() -> None:
        """Add update entities for devices."""
        entities: list[ESPHomeDashboardUpdateEntity] = []

        for device_name, device_data in coordinator.data.items():
            if device_name not in known_devices:
                known_devices.add(device_name)
                # Try to find MAC address for existing ESPHome device
                mac_address = _find_esphome_device_mac(hass, device_name)
                entities.append(
                    ESPHomeDashboardUpdateEntity(
                        coordinator, device_name, device_data, mac_address
                    )
                )

        if entities:
            async_add_entities(entities)

    # Add entities on initial setup
    async_add_update_entities()

    # Add entities when new devices are discovered and register cleanup
    entry.async_on_unload(coordinator.async_add_listener(async_add_update_entities))


class ESPHomeDashboardUpdateEntity(
    CoordinatorEntity[ESPHomeDashboardCoordinator], UpdateEntity
):
    """Representation of an ESPHome device firmware update status."""

    _attr_has_entity_name = True
    _attr_name = "Firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_release_url = ESPHOME_CHANGELOG_URL

    def __init__(
        self,
        coordinator: ESPHomeDashboardCoordinator,
        device_name: str,
        device_data: ConfiguredDevice,
        mac_address: str | None,
    ) -> None:
        """Initialize the update entity."""
        super().__init__(coordinator)

        # config_entry is always set for this coordinator
        assert coordinator.config_entry is not None
        entry_id = coordinator.config_entry.entry_id

        self._device_name = device_name
        self._attr_unique_id = f"{entry_id}_{device_name}"

        # Store configuration metadata
        self._configuration = device_data.get("configuration", f"{device_name}.yaml")
        self._address: str | None = None
        self._dashboard_status: str | None = None
        self._dashboard_comment: str | None = None
        self._dashboard_deployed_version: str | None = None
        self._raw_latest_version: str | None = None

        # Version tracking - prefer esphome integration version over dashboard
        self._esphome_entry_data: RuntimeEntryData | None = None
        self._cached_device_version: str | None = None
        self._esphome_unsubscribe: CALLBACK_TYPE | None = None

        # Build configuration URL from dashboard URL
        dashboard_url = coordinator.config_entry.data[CONF_URL]
        configuration_url = f"{dashboard_url.rstrip('/')}/"

        # Link to existing ESPHome device using MAC address connection
        if mac_address:
            self._attr_device_info = DeviceInfo(
                connections={(CONNECTION_NETWORK_MAC, mac_address)},
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry_id}_{device_name}")},
                name=device_name,
                manufacturer="ESPHome",
                configuration_url=configuration_url,
            )

        self._update_attrs(device_data)

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()

        # Try to find esphome integration entry for this device
        self._esphome_entry_data = _find_esphome_entry_data(
            self.hass, self._device_name
        )

        if self._esphome_entry_data:
            # Subscribe to device updates for version changes
            self._esphome_unsubscribe = (
                self._esphome_entry_data.async_subscribe_device_updated(
                    self._handle_esphome_device_update
                )
            )
            # Update state immediately with esphome version
            self.async_write_ha_state()
        elif self._address:
            # Not in esphome integration - query device directly
            self.hass.async_create_task(self._async_fetch_device_version())

    async def _async_discover_device_port(self) -> int | None:
        """Discover device port via mDNS."""
        try:
            aiozc = await zeroconf.async_get_async_instance(self.hass)
            service_name = f"{self._device_name}.{ESPHOME_SERVICE_TYPE}"

            info = AsyncServiceInfo(ESPHOME_SERVICE_TYPE, service_name)
            if await info.async_request(aiozc.zeroconf, timeout=3.0):
                return info.port
        except (TimeoutError, OSError, AttributeError):
            pass
        return None

    async def _async_query_device_version(self, address: str) -> str | None:
        """Query device version directly via native API."""
        port = await self._async_discover_device_port() or DEFAULT_PORT

        zeroconf_instance = await zeroconf.async_get_instance(self.hass)
        client = APIClient(
            address, port=port, password="", zeroconf_instance=zeroconf_instance
        )
        try:
            await client.connect(login=False)
            device_info = await client.device_info()
            return device_info.esphome_version
        except APIConnectionError:
            return None
        finally:
            await client.disconnect()

    async def _async_fetch_device_version(self) -> None:
        """Fetch device version via direct API query."""
        if not self._address:
            return

        version = await self._async_query_device_version(self._address)
        if version:
            self._cached_device_version = version
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity being removed from Home Assistant."""
        if self._esphome_unsubscribe:
            self._esphome_unsubscribe()
            self._esphome_unsubscribe = None

    @callback
    def _handle_esphome_device_update(self) -> None:
        """Handle device update from esphome integration."""
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if not self._esphome_entry_data:
            entry_data = _find_esphome_entry_data(self.hass, self._device_name)
            if entry_data:
                self._esphome_entry_data = entry_data
                self._esphome_unsubscribe = entry_data.async_subscribe_device_updated(
                    self._handle_esphome_device_update
                )
                self._cached_device_version = None

        if self._device_name in self.coordinator.data:
            self._update_attrs(self.coordinator.data[self._device_name])
        else:
            self._attr_available = False

        self.async_write_ha_state()

    def _update_attrs(self, device_data: ConfiguredDevice) -> None:
        """Update entity attributes from device data."""
        self._address = device_data.get("address")
        self._dashboard_deployed_version = device_data.get("deployed_version")
        self._raw_latest_version = device_data.get("current_version")
        self._dashboard_status = device_data.get("status")
        self._dashboard_comment = device_data.get("comment")

        # Enable install feature if device has an address for OTA
        if self._address:
            self._attr_supported_features = (
                UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES
            )
        else:
            self._attr_supported_features = UpdateEntityFeature.RELEASE_NOTES

    @property
    def installed_version(self) -> str | None:
        """Return installed version with priority: esphome > cached > dashboard."""
        if self._esphome_entry_data and self._esphome_entry_data.device_info:
            return self._esphome_entry_data.device_info.esphome_version
        if self._cached_device_version:
            return self._cached_device_version
        return self._dashboard_deployed_version

    @property
    def latest_version(self) -> str | None:
        """Return latest version with optional stale indicator."""
        version = self._raw_latest_version or self._dashboard_deployed_version
        if version and self.reinstall_useful:
            return f"{version}*"
        return version

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._device_name in self.coordinator.data and self.is_online

    @property
    def is_online(self) -> bool:
        """Return if the device is currently online."""
        if not self._esphome_entry_data:
            self._esphome_entry_data = _find_esphome_entry_data(self.hass, self._device_name)
        return self._esphome_entry_data.available if self._esphome_entry_data else False

    @property
    def reinstall_useful(self) -> bool:
        """Return True if YAML has changed and a reinstall is useful."""
        return self._dashboard_status == "STALE"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            ATTR_CONFIGURATION: self._configuration,
            "dashboard_status": self._dashboard_status,
            "dashboard_comment": self._dashboard_comment,
            "reinstall_useful": self.reinstall_useful,
        }

    async def async_release_notes(self) -> str | None:
        """Return release notes for the latest ESPHome version."""
        installed = self.installed_version
        latest = self._raw_latest_version or self._dashboard_deployed_version
        if not latest:
            return None

        notes = f"## ESPHome {latest}\n\n"
        if self.reinstall_useful:
            notes += "**Warning:** The device configuration (YAML) has changed since the last build. A reinstall is recommended even if the version matches.\n\n"
        
        if installed and installed != latest:
            notes += f"Updating from **{installed}** to **{latest}**.\n\n"

        parts = latest.split(".")
        if len(parts) >= 2:
            changelog_version = f"{parts[0]}.{parts[1]}.0"
            notes += f"See the full changelog at {ESPHOME_CHANGELOG_URL}{changelog_version}.html"

        return notes

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Install an update."""
        if not self._address:
            raise HomeAssistantError(f"No address available for {self._device_name}")

        _LOGGER.info("Starting update for %s to %s", self._device_name, self._configuration)
        api = self.coordinator.api

        if not await api.compile(self._configuration):
            raise HomeAssistantError(f"Failed to compile {self._configuration}")

        _LOGGER.info("Compilation successful for %s", self._device_name)

        if not self.is_online:
            raise ServiceValidationError(
                f"{self._device_name} is currently offline. Firmware has been compiled and is ready to be uploaded once the device appears online."
            )

        if not await api.upload(self._configuration, self._address):
            raise HomeAssistantError(f"Failed to upload to {self._device_name} at {self._address}")

        _LOGGER.info("Successfully updated %s", self._device_name)
        self._cached_device_version = None
        await self.coordinator.async_request_refresh()
        if not self._esphome_entry_data and self._address:
            await self._async_fetch_device_version()
