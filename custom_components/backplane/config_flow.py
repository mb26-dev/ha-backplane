"""Config flow for Backplane."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback

from .const import (
    CONF_COMMUNITY,
    CONF_PORT_FILTER,
    CONF_SCAN_INTERVAL,
    DEFAULT_COMMUNITY,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SYS_DESCR,
    SYS_NAME,
)
from .snmp import SnmpClient, SnmpError, SnmpTimeout


async def _probe(host: str, community: str, port: int) -> dict[str, str]:
    client = SnmpClient(host, community, port, timeout=4.0, retries=1)
    try:
        values = await client.get([SYS_DESCR, SYS_NAME])
    finally:
        client.close()
    if SYS_DESCR not in values:
        raise SnmpError("sysDescr not readable")

    def text(raw: object) -> str:
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace").strip()
        return str(raw or "").strip()

    return {"descr": text(values.get(SYS_DESCR)), "name": text(values.get(SYS_NAME))}


class BackplaneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a switch."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            community = user_input[CONF_COMMUNITY]
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()
            try:
                info = await _probe(host, community, port)
            except SnmpTimeout:
                errors["base"] = "cannot_connect"
            except (SnmpError, OSError):
                errors["base"] = "cannot_connect"
            else:
                title = (user_input.get(CONF_NAME) or "").strip() or info["name"] or host
                return self.async_create_entry(
                    title=title,
                    data={CONF_HOST: host, CONF_PORT: port, CONF_COMMUNITY: community},
                    options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
                )

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_COMMUNITY, default=defaults.get(CONF_COMMUNITY, DEFAULT_COMMUNITY)
                ): str,
                vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return BackplaneOptionsFlow()


class BackplaneOptionsFlow(OptionsFlow):
    """Polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            pattern = (user_input.get(CONF_PORT_FILTER) or "").strip()
            try:
                if pattern:
                    re.compile(pattern)
            except re.error:
                errors[CONF_PORT_FILTER] = "invalid_regex"
            else:
                return self.async_create_entry(
                    data={**user_input, CONF_PORT_FILTER: pattern}
                )
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        current_filter = self.config_entry.options.get(CONF_PORT_FILTER, "")
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Optional(CONF_PORT_FILTER, default=current_filter): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
