"""Hardware health binary sensors (fan / power supply) for Backplane."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BackplaneConfigEntry
from .coordinator import BackplaneCoordinator
from .entity import BackplaneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BackplaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    sensors = (coordinator.data or {}).get("sensors", [])
    async_add_entities(
        BackplaneHealthSensor(coordinator, item["id"], item["name"]) for item in sensors
    )


class BackplaneHealthSensor(BackplaneEntity, BinarySensorEntity):
    """On = problem."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BackplaneCoordinator, sensor_id: int, name: str) -> None:
        super().__init__(coordinator, f"health_{sensor_id}")
        self._sensor_id = sensor_id
        self._attr_name = name.replace(" Sensor", "").strip() or f"Sensor {sensor_id}"

    def _item(self) -> dict | None:
        for item in (self.coordinator.data or {}).get("sensors", []):
            if item["id"] == self._sensor_id:
                return item
        return None

    @property
    def is_on(self) -> bool | None:
        item = self._item()
        if item is None or item["status"] in ("unknown", "not_present"):
            return None
        return item["status"] in ("bad", "warning")

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        item = self._item()
        return {"status": item["status"]} if item else {}
