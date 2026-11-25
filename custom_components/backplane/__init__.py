"""Backplane - live SNMP switch visualization for Home Assistant."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CARD_FILENAME, DOMAIN, URL_BASE, VERSION
from .coordinator import BackplaneCoordinator
from .health import render_report

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type BackplaneConfigEntry = ConfigEntry[BackplaneCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled Lovelace card and load it in every dashboard."""
    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(www), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILENAME}?v={VERSION}")

    async def _health_report(call: ServiceCall) -> ServiceResponse:
        devices = []
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is not ConfigEntryState.LOADED:
                continue
            data = entry.runtime_data.data
            if not data:
                continue
            devices.append({"title": entry.title, **data})
        devices.sort(key=lambda d: d["health"]["score"])
        report_html, report_text = render_report(devices)
        return {
            "html": report_html,
            "text": report_text,
            "devices": [
                {
                    "title": d["title"],
                    "host": d["system"]["host"],
                    "score": d["health"]["score"],
                    "grade": d["health"]["grade"],
                    "findings": d["health"]["findings"],
                }
                for d in devices
            ],
        }

    hass.services.async_register(
        DOMAIN, "health_report", _health_report, supports_response=SupportsResponse.ONLY
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BackplaneConfigEntry) -> bool:
    """Set up one switch."""
    coordinator = BackplaneCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: BackplaneConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BackplaneConfigEntry) -> bool:
    """Unload a switch."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.client.close()
    return unloaded
