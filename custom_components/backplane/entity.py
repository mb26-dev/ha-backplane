"""Base entity for Backplane."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BackplaneCoordinator


class BackplaneEntity(CoordinatorEntity[BackplaneCoordinator]):
    """Common device info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BackplaneCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        static = coordinator.static
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer=(static.manufacturer if static else None) or None,
            model=(static.model if static else None) or None,
            sw_version=(static.firmware if static else None) or None,
            configuration_url=f"http://{coordinator.host}",
        )
