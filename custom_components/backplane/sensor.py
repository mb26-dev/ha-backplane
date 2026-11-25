"""Sensors for Backplane."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BackplaneConfigEntry
from .coordinator import BackplaneCoordinator
from .entity import BackplaneEntity


@dataclass(frozen=True, kw_only=True)
class BackplaneSensorDescription(SensorEntityDescription):
    """Describes a Backplane sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    available_fn: Callable[[dict[str, Any]], bool] = lambda data: True


def _mbit(value: float) -> float:
    return round(value / 1_000_000, 2)


SENSORS: tuple[BackplaneSensorDescription, ...] = (
    BackplaneSensorDescription(
        key="traffic_in",
        translation_key="traffic_in",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: _mbit(d["totals"]["in"]),
    ),
    BackplaneSensorDescription(
        key="traffic_out",
        translation_key="traffic_out",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: _mbit(d["totals"]["out"]),
    ),
    BackplaneSensorDescription(
        key="ports_up",
        translation_key="ports_up",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d["totals"]["up"],
    ),
    BackplaneSensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d["system"]["cpu"],
        available_fn=lambda d: d["system"]["cpu"] is not None,
    ),
    BackplaneSensorDescription(
        key="poe_power",
        translation_key="poe_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d["poe"]["used"],
        available_fn=lambda d: d["poe"] is not None,
    ),
    BackplaneSensorDescription(
        key="poe_budget",
        translation_key="poe_budget",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d["poe"]["budget"],
        available_fn=lambda d: d["poe"] is not None,
    ),
    BackplaneSensorDescription(
        key="boot_time",
        translation_key="boot_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: datetime.fromtimestamp(d["system"]["boot_ts"], tz=UTC),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BackplaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        BackplaneMapSensor(coordinator),
        BackplaneHealthSensor(coordinator),
    ]
    data = coordinator.data or {}
    for description in SENSORS:
        if description.key == "cpu" and data.get("system", {}).get("cpu") is None:
            continue
        if description.key.startswith("poe") and not data.get("poe"):
            continue
        entities.append(BackplaneSensor(coordinator, description))
    async_add_entities(entities)


class BackplaneSensor(BackplaneEntity, SensorEntity):
    """Scalar switch metric."""

    entity_description: BackplaneSensorDescription

    def __init__(
        self, coordinator: BackplaneCoordinator, description: BackplaneSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self.entity_description.available_fn(self.coordinator.data)
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)


class BackplaneMapSensor(BackplaneEntity, SensorEntity):
    """Full port map for the Backplane card (attributes are not recorded)."""

    _attr_translation_key = "port_map"
    _attr_icon = "mdi:switch"
    _unrecorded_attributes = frozenset(
        {"backplane", "system", "ports", "poe", "sensors", "totals", "ts", "health"}
    )

    def __init__(self, coordinator: BackplaneCoordinator) -> None:
        super().__init__(coordinator, "port_map")

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        return data["totals"]["up"] if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {"backplane": True}
        return {
            "backplane": True,
            "system": data["system"],
            "ports": data["ports"],
            "poe": data["poe"],
            "sensors": data["sensors"],
            "totals": data["totals"],
            "health": data.get("health"),
            "ts": data["ts"],
        }


class BackplaneHealthSensor(BackplaneEntity, SensorEntity):
    """Health score 0-100 with findings."""

    _attr_translation_key = "health"
    _attr_icon = "mdi:heart-pulse"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"findings"})

    def __init__(self, coordinator: BackplaneCoordinator) -> None:
        super().__init__(coordinator, "health")

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        return data["health"]["score"] if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {}
        health = data["health"]
        return {
            "grade": health["grade"],
            "critical": sum(1 for f in health["findings"] if f["level"] == "critical"),
            "warnings": sum(1 for f in health["findings"] if f["level"] == "warning"),
            "findings": health["findings"],
        }
