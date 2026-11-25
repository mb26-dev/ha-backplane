"""Diagnostics for Backplane."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import BackplaneConfigEntry
from .const import CONF_AUTH_PASSWORD, CONF_COMMUNITY, CONF_PRIV_PASSWORD, CONF_V3_USER

TO_REDACT = {CONF_COMMUNITY, CONF_AUTH_PASSWORD, CONF_PRIV_PASSWORD, CONF_V3_USER, "m", "ip"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BackplaneConfigEntry
) -> dict[str, Any]:
    """Return redacted entry data and the latest poll."""
    coordinator = entry.runtime_data
    static = coordinator.static
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "discovery": None
        if static is None
        else {
            "descr": static.descr,
            "is_hp": static.is_hp,
            "ports": {str(k): v for k, v in static.ports.items()},
            "lag_members": {str(k): v for k, v in static.lag_members.items()},
            "has_poe": static.has_poe,
            "has_hp_poe_power": static.has_hp_poe_power,
            "has_cpu": static.has_cpu,
            "has_dot3": static.has_dot3,
            "hr_cpus": static.hr_cpus,
            "sensors": static.sensors,
            "neighbors": len(static.neighbors),
        },
        "data": async_redact_data(coordinator.data or {}, TO_REDACT),
    }
