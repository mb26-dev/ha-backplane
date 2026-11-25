"""PoE restart buttons for Backplane."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BackplaneConfigEntry
from .coordinator import BackplaneCoordinator
from .entity import BackplaneEntity
from .snmp import SnmpError, SnmpTimeout


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BackplaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    ports = (coordinator.data or {}).get("ports", [])
    async_add_entities(
        BackplanePoeRestartButton(coordinator, port["i"], port["n"])
        for port in ports
        if port.get("k") == "eth" and "poe" in port
    )


class BackplanePoeRestartButton(BackplaneEntity, ButtonEntity):
    """Power-cycle PoE on one port. Needs SNMP write access (disabled by default)."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "poe_restart"

    def __init__(self, coordinator: BackplaneCoordinator, index: int, name: str) -> None:
        super().__init__(coordinator, f"port_{index}_poe_restart")
        self._index = index
        self._attr_translation_placeholders = {"port": name}

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_restart_poe(self._index)
        except SnmpTimeout as err:
            raise HomeAssistantError(
                translation_domain="backplane", translation_key="poe_timeout"
            ) from err
        except SnmpError as err:
            raise HomeAssistantError(
                translation_domain="backplane", translation_key="poe_refused"
            ) from err
