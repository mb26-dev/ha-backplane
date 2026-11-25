"""Config flow for Backplane (SNMP v2c / v3, reconfigure, options)."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_AUTH_PASSWORD,
    CONF_AUTH_PROTOCOL,
    CONF_COMMUNITY,
    CONF_PORT_EVENTS,
    CONF_PORT_FILTER,
    CONF_PRIV_PASSWORD,
    CONF_PRIV_PROTOCOL,
    CONF_SCAN_INTERVAL,
    CONF_SNMP_VERSION,
    CONF_V3_USER,
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
from .usm import SnmpAuthError, V3Params

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def build_client(data: dict[str, Any], timeout: float = 3.0, retries: int = 2) -> SnmpClient:
    """Create an SNMP client from config entry data."""
    host = data[CONF_HOST]
    port = int(data.get(CONF_PORT, DEFAULT_PORT))
    if data.get(CONF_SNMP_VERSION, "v2c") == "v3":
        priv = data.get(CONF_PRIV_PROTOCOL, "aes")
        v3 = V3Params(
            user=data[CONF_V3_USER],
            auth_protocol=data.get(CONF_AUTH_PROTOCOL, "sha"),
            auth_password=data.get(CONF_AUTH_PASSWORD, ""),
            priv_protocol=None if priv == "none" else priv,
            priv_password=data.get(CONF_PRIV_PASSWORD, ""),
        )
        return SnmpClient(host, "", port, timeout=timeout, retries=retries, v3=v3)
    return SnmpClient(
        host, data.get(CONF_COMMUNITY, DEFAULT_COMMUNITY), port, timeout=timeout, retries=retries
    )


async def _probe(data: dict[str, Any]) -> dict[str, str]:
    client = build_client(data, timeout=4.0, retries=1)
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


def _schema(defaults: dict[str, Any], include_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_SNMP_VERSION, default=defaults.get(CONF_SNMP_VERSION, "v2c")): SelectSelector(
            SelectSelectorConfig(
                options=["v2c", "v3"], mode=SelectSelectorMode.LIST, translation_key="snmp_version"
            )
        ),
        vol.Optional(CONF_COMMUNITY, default=defaults.get(CONF_COMMUNITY, DEFAULT_COMMUNITY)): str,
        vol.Optional(CONF_V3_USER, default=defaults.get(CONF_V3_USER, "")): str,
        vol.Optional(CONF_AUTH_PROTOCOL, default=defaults.get(CONF_AUTH_PROTOCOL, "sha")): SelectSelector(
            SelectSelectorConfig(
                options=["md5", "sha", "sha256"],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="auth_protocol",
            )
        ),
        vol.Optional(CONF_AUTH_PASSWORD, default=defaults.get(CONF_AUTH_PASSWORD, "")): _PASSWORD,
        vol.Optional(CONF_PRIV_PROTOCOL, default=defaults.get(CONF_PRIV_PROTOCOL, "aes")): SelectSelector(
            SelectSelectorConfig(
                options=["none", "aes", "des"],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="priv_protocol",
            )
        ),
        vol.Optional(CONF_PRIV_PASSWORD, default=defaults.get(CONF_PRIV_PASSWORD, "")): _PASSWORD,
    }
    if include_name:
        fields[vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, ""))] = str
    return vol.Schema(fields)


def _clean(user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate and normalise the form; return (data, errors)."""
    errors: dict[str, str] = {}
    data: dict[str, Any] = {
        CONF_HOST: user_input[CONF_HOST].strip(),
        CONF_PORT: int(user_input[CONF_PORT]),
        CONF_SNMP_VERSION: user_input.get(CONF_SNMP_VERSION, "v2c"),
    }
    if data[CONF_SNMP_VERSION] == "v3":
        user = (user_input.get(CONF_V3_USER) or "").strip()
        auth_pw = user_input.get(CONF_AUTH_PASSWORD) or ""
        priv = user_input.get(CONF_PRIV_PROTOCOL, "aes")
        priv_pw = user_input.get(CONF_PRIV_PASSWORD) or ""
        if not user:
            errors[CONF_V3_USER] = "required"
        if len(auth_pw) < 8:
            errors[CONF_AUTH_PASSWORD] = "password_too_short"
        if priv != "none" and len(priv_pw or auth_pw) < 8:
            errors[CONF_PRIV_PASSWORD] = "password_too_short"
        data.update(
            {
                CONF_V3_USER: user,
                CONF_AUTH_PROTOCOL: user_input.get(CONF_AUTH_PROTOCOL, "sha"),
                CONF_AUTH_PASSWORD: auth_pw,
                CONF_PRIV_PROTOCOL: priv,
                CONF_PRIV_PASSWORD: priv_pw,
            }
        )
    else:
        community = (user_input.get(CONF_COMMUNITY) or "").strip()
        if not community:
            errors[CONF_COMMUNITY] = "required"
        data[CONF_COMMUNITY] = community
    return data, errors


async def _validate(data: dict[str, Any]) -> tuple[dict[str, str] | None, dict[str, str]]:
    try:
        return await _probe(data), {}
    except SnmpAuthError:
        return None, {"base": "invalid_auth"}
    except (SnmpTimeout, SnmpError, OSError):
        return None, {"base": "cannot_connect"}


class BackplaneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a switch."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _clean(user_input)
            if not errors:
                await self.async_set_unique_id(f"{data[CONF_HOST]}:{data[CONF_PORT]}")
                self._abort_if_unique_id_configured()
                info, errors = await _validate(data)
                if info is not None:
                    title = (user_input.get(CONF_NAME) or "").strip() or info["name"] or data[CONF_HOST]
                    return self.async_create_entry(
                        title=title, data=data, options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL}
                    )
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}, True), errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _clean(user_input)
            if not errors:
                new_id = f"{data[CONF_HOST]}:{data[CONF_PORT]}"
                if new_id != entry.unique_id:
                    await self.async_set_unique_id(new_id)
                    self._abort_if_unique_id_configured()
                info, errors = await _validate(data)
                if info is not None:
                    return self.async_update_reload_and_abort(entry, unique_id=new_id, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data), False),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return BackplaneOptionsFlow()


class BackplaneOptionsFlow(OptionsFlow):
    """Polling interval, port filter, port events."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            pattern = (user_input.get(CONF_PORT_FILTER) or "").strip()
            try:
                if pattern:
                    re.compile(pattern)
            except re.error:
                errors[CONF_PORT_FILTER] = "invalid_regex"
            else:
                return self.async_create_entry(data={**user_input, CONF_PORT_FILTER: pattern})
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                vol.Optional(CONF_PORT_FILTER, default=options.get(CONF_PORT_FILTER, "")): str,
                vol.Optional(CONF_PORT_EVENTS, default=options.get(CONF_PORT_EVENTS, True)): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
