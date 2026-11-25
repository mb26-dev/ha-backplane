"""Data coordinator for Backplane: discovery + fast polling of one switch."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AUTO_EXCLUDE,
    CONF_PORT_EVENTS,
    DOT1D_BASE_PORT_IFINDEX,
    DOT1D_TP_FDB_PORT,
    DOT1Q_TP_FDB_PORT,
    EVENT_PORT,
    FDB_INTERVAL,
    IP_NET_TO_MEDIA_PHYS,
    MAX_MACS_PER_PORT,
    CONF_PORT_FILTER,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DISCOVERY_INTERVAL,
    DOT3_DUPLEX,
    DOT3_FCS_ERRORS,
    DOMAIN,
    DOT1Q_PVID,
    DOT1Q_VLAN_NAME,
    HR_PROCESSOR_LOAD,
    HP_CPU,
    HP_ENTERPRISE,
    HP_POE_PORT_POWER_MW,
    HP_SENSOR_DESCR,
    HP_SENSOR_STATES,
    HP_SENSOR_STATUS,
    IF_ADMIN_STATUS,
    IF_ALIAS,
    IF_HC_IN_OCTETS,
    IF_HC_OUT_OCTETS,
    IF_HIGH_SPEED,
    IF_IN_ERRORS,
    IF_LAST_CHANGE,
    IF_NAME,
    IF_OPER_STATUS,
    IF_OUT_ERRORS,
    IF_STACK_STATUS,
    IF_TYPE,
    IFTYPE_ETHERNET,
    IFTYPE_LAG,
    LLDP_LOC_PORT_ID,
    LLDP_REM_PORT_DESC,
    LLDP_REM_PORT_ID,
    LLDP_REM_SYS_DESC,
    LLDP_REM_SYS_NAME,
    PETH_DETECTION_STATES,
    PETH_MAIN_CONSUMPTION,
    PETH_MAIN_POWER,
    PETH_MAIN_STATUS,
    PETH_PORT_DETECTION,
    SYS_DESCR,
    SYS_LOCATION,
    SYS_NAME,
    SYS_OBJECT_ID,
    SYS_UPTIME,
)
from .config_flow import build_client
from .health import evaluate
from .snmp import Oid, SnmpClient, SnmpError, SnmpTimeout
from .vendors import detect_vendor

_LOGGER = logging.getLogger(__name__)

# Small vendor table (IEEE OUI) for devices Home Assistant does not know
_OUI = {
    "00:08:9b": "QNAP",
    "24:5e:be": "QNAP",
    "00:11:32": "Synology",
    "90:09:d0": "Synology",
    "bc:24:11": "Proxmox VM",
    "52:54:00": "QEMU/KVM VM",
    "9c:c7:a6": "AVM",
    "34:31:c4": "AVM",
    "c0:25:06": "AVM",
    "00:c0:b7": "APC",
    "00:03:c5": "Mobotix",
    "68:54:fd": "Amazon",
    "b8:27:eb": "Raspberry Pi",
    "dc:a6:32": "Raspberry Pi",
    "e4:5f:01": "Raspberry Pi",
    "d8:3a:dd": "Raspberry Pi",
    "00:0c:29": "VMware VM",
    "00:50:56": "VMware VM",
}


def _vendor(mac: str) -> str | None:
    vendor = _OUI.get(mac[:8])
    if vendor:
        return vendor
    if int(mac[:2], 16) & 0x02:
        return "random / virtual"
    return None


_LAG_NAME = re.compile(r"^(trk|dyn|po|port-channel|lag|bond|ae)\d+", re.IGNORECASE)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00").strip()
    return str(value).strip()


def _printable(value: Any) -> str:
    """Decode an OCTET STRING; render binary values (MACs) as hex."""
    if isinstance(value, bytes):
        if value and all(32 <= b < 127 for b in value):
            return value.decode("ascii")
        return ":".join(f"{b:02x}" for b in value)
    return _text(value)


def _device_for_mac(registry: dr.DeviceRegistry, mac: str) -> dr.DeviceEntry | None:
    """Look up a device by MAC across HA versions."""
    conn = (dr.CONNECTION_NETWORK_MAC, mac)
    for name in ("async_get_device_by_connection", "async_get_devices"):
        func = getattr(registry, name, None)
        if func is None:
            continue
        for call in (lambda f=func: f(conn), lambda f=func: f(connections={conn})):
            try:
                found = call()
            except TypeError:
                continue
            if found is None or isinstance(found, dr.DeviceEntry):
                return found
            return next(iter(found), None)
    return registry.async_get_device(connections={conn})


@dataclass
class StaticInfo:
    """Slow-changing switch facts, re-read every DISCOVERY_INTERVAL."""

    name: str = ""
    descr: str = ""
    model: str = ""
    manufacturer: str = ""
    firmware: str = ""
    location: str = ""
    is_hp: bool = False
    ports: dict[int, dict[str, Any]] = field(default_factory=dict)
    lag_members: dict[int, list[int]] = field(default_factory=dict)
    neighbors: dict[int, dict[str, str]] = field(default_factory=dict)
    vlans: dict[int, str] = field(default_factory=dict)
    pvid: dict[int, int] = field(default_factory=dict)
    sensors: dict[int, str] = field(default_factory=dict)
    has_poe: bool = False
    has_hp_poe_power: bool = False
    has_cpu: bool = False
    has_dot3: bool = False
    hr_cpus: list[int] = field(default_factory=list)


def _parse_descr(descr: str) -> tuple[str, str, str]:
    """Return (manufacturer, model, firmware) from sysDescr."""
    firmware = ""
    match = re.search(r"revision\s+([\w.\-]+)", descr, re.IGNORECASE)
    if match:
        firmware = match.group(1)
    else:
        match = re.search(r"version\s+([\w.\-()]+)", descr, re.IGNORECASE)
        if match:
            firmware = match.group(1).rstrip(",")
    linux = re.match(r"^Linux\s+(\S+)\s+(\S+)", descr)
    if linux:
        return "Linux", "Router", linux.group(2)
    head = descr.split(",")[0].strip()
    manufacturer = head.split(" ")[0] if head else ""
    model = head
    # "HP J9773A 2530-24G-PoEP Switch" -> "2530-24G-PoEP"
    hp = re.match(r"^(HP|Aruba|HPE)\s+\w+\s+(.+?)(\s+Switch)?$", head)
    if hp:
        model = hp.group(2)
    return manufacturer, model, firmware


class BackplaneCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls one switch."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=interval),
        )
        self.host: str = entry.data[CONF_HOST]
        self.client = build_client(dict(entry.data))
        self._events = bool(entry.options.get(CONF_PORT_EVENTS, True))
        self._prev_speed: dict[int, int] = {}
        self._fdb: dict[int, list[str]] = {}
        self._arp: dict[str, str] = {}
        self._fdb_ts = 0.0
        self.static: StaticInfo | None = None
        self._static_ts = 0.0
        self._counters: dict[int, tuple[float, int, int]] = {}
        self._boot_ts: float | None = None
        # health history (1 h window)
        self._err_hist: dict[int, deque[tuple[float, int]]] = {}
        self._flap_hist: dict[int, deque[float]] = {}
        self._prev_oper: dict[int, int] = {}
        custom = (entry.options.get(CONF_PORT_FILTER) or "").strip()
        try:
            self._port_filter = re.compile(custom) if custom else None
        except re.error:
            _LOGGER.warning("Invalid port filter %r ignored", custom)
            self._port_filter = None
        self._auto_exclude = re.compile(AUTO_EXCLUDE, re.IGNORECASE)

    async def async_shutdown(self) -> None:
        """Close the socket when the entry unloads."""
        await super().async_shutdown()
        self.client.close()

    # ------------------------------------------------------------ discovery

    async def _discover(self) -> StaticInfo:
        client = self.client
        info = StaticInfo()

        system = await client.get([SYS_DESCR, SYS_OBJECT_ID, SYS_NAME, SYS_LOCATION])
        if SYS_DESCR not in system:
            raise SnmpError("sysDescr not readable")
        info.descr = _text(system.get(SYS_DESCR))
        info.name = _text(system.get(SYS_NAME)) or self.host
        info.location = _text(system.get(SYS_LOCATION))
        object_id = system.get(SYS_OBJECT_ID)
        info.is_hp = isinstance(object_id, tuple) and object_id[:7] == HP_ENTERPRISE
        info.manufacturer, info.model, info.firmware = _parse_descr(info.descr)
        vendor = detect_vendor(object_id, info.descr)
        if vendor:
            info.manufacturer = vendor

        types = await client.walk(IF_TYPE)
        names = await client.walk(IF_NAME)
        aliases = await client.walk(IF_ALIAS)

        all_names = {_text(v) for v in names.values()}
        has_switch_ports = any(re.match(r"^(lan\d+|wan\d*)$", n) for n in all_names)
        for suffix, if_type in sorted(types.items()):
            index = suffix[0]
            name = _text(names.get(suffix)) or str(index)
            if if_type == IFTYPE_LAG or (_LAG_NAME.match(name) and if_type != 24):
                kind = "lag"
            elif if_type in IFTYPE_ETHERNET:
                kind = "eth"
            else:
                continue
            if self._port_filter is not None:
                if not self._port_filter.search(name):
                    continue
            else:
                if self._auto_exclude.match(name):
                    continue
                # DSA conduit (eth0) carries the switch ports on OpenWrt
                if has_switch_ports and re.match(r"^eth\d+$", name):
                    continue
            info.ports[index] = {
                "name": name,
                "alias": _text(aliases.get(suffix)),
                "kind": kind,
            }

        # trunk membership via ifStackTable (higher = trunk, lower = member)
        stack = await client.walk(IF_STACK_STATUS)
        for suffix in stack:
            if len(suffix) != 2:
                continue
            higher, lower = suffix
            if higher in info.ports and info.ports[higher]["kind"] == "lag":
                if lower in info.ports and info.ports[lower]["kind"] == "eth":
                    info.lag_members.setdefault(higher, []).append(lower)
        for members in info.lag_members.values():
            members.sort()

        # VLANs
        for suffix, value in (await client.walk(DOT1Q_VLAN_NAME)).items():
            info.vlans[suffix[-1]] = _text(value)
        for suffix, value in (await client.walk(DOT1Q_PVID)).items():
            if isinstance(value, int):
                info.pvid[suffix[0]] = value

        # LLDP neighbours: local port number -> ifIndex
        local_ids = await client.walk(LLDP_LOC_PORT_ID)
        name_to_index = {p["name"]: i for i, p in info.ports.items()}
        local_to_if: dict[int, int] = {}
        for suffix, value in local_ids.items():
            local = suffix[0]
            port_id = _printable(value)
            if port_id in name_to_index:
                local_to_if[local] = name_to_index[port_id]
            elif local in info.ports:
                local_to_if[local] = local
        rem_name = await client.walk(LLDP_REM_SYS_NAME)
        rem_port = await client.walk(LLDP_REM_PORT_ID)
        rem_pdesc = await client.walk(LLDP_REM_PORT_DESC)
        rem_desc = await client.walk(LLDP_REM_SYS_DESC)
        for suffix in set(rem_name) | set(rem_port):
            if len(suffix) < 3:
                continue
            local = suffix[1]
            if_index = local_to_if.get(local, local)
            if if_index not in info.ports:
                continue
            info.neighbors[if_index] = {
                "name": _printable(rem_name.get(suffix)),
                "port": _printable(rem_pdesc.get(suffix))
                or _printable(rem_port.get(suffix)),
                "descr": _text(rem_desc.get(suffix))[:120],
            }

        # EtherLike-MIB (duplex, FCS) - probe on the first ethernet port
        first_eth = next((i for i, p in info.ports.items() if p["kind"] == "eth"), None)
        if first_eth is not None:
            dot3 = await client.get([DOT3_DUPLEX + (first_eth,)])
            info.has_dot3 = bool(dot3)

        # PoE capability
        poe = await client.get([PETH_MAIN_POWER])
        info.has_poe = PETH_MAIN_POWER in poe

        if not info.is_hp:
            loads = await client.walk(HR_PROCESSOR_LOAD)
            info.hr_cpus = sorted(suffix[0] for suffix in loads)
        if info.is_hp:
            hp = await client.get([HP_CPU])
            info.has_cpu = HP_CPU in hp
            for suffix, value in (await client.walk(HP_SENSOR_DESCR)).items():
                info.sensors[suffix[0]] = _text(value)
            if info.has_poe:
                probe = await client.walk(HP_POE_PORT_POWER_MW, max_repetitions=8)
                info.has_hp_poe_power = bool(probe)

        _LOGGER.debug(
            "Discovered %s: %s ports, %s trunks, %s neighbours, poe=%s",
            self.host,
            len(info.ports),
            len(info.lag_members),
            len(info.neighbors),
            info.has_poe,
        )
        return info

    # ------------------------------------------------------------ MAC table

    async def _refresh_fdb(self, info: StaticInfo) -> None:
        """Read the forwarding database (MAC -> port) and, on routers, the ARP table."""
        client = self.client
        base = await client.walk(DOT1D_BASE_PORT_IFINDEX, max_repetitions=16)
        bridge_to_if = {k[0]: v for k, v in base.items() if isinstance(v, int)}
        fdb_raw = await client.walk(DOT1Q_TP_FDB_PORT, max_repetitions=16)
        mac_offset = 1  # index = fdbId.m1..m6
        if not fdb_raw:
            fdb_raw = await client.walk(DOT1D_TP_FDB_PORT, max_repetitions=16)
            mac_offset = 0
        fdb: dict[int, list[str]] = {}
        for suffix, bridge_port in fdb_raw.items():
            if not isinstance(bridge_port, int) or bridge_port == 0:
                continue
            mac_parts = suffix[mac_offset : mac_offset + 6]
            if len(mac_parts) != 6:
                continue
            mac = ":".join(f"{b:02x}" for b in mac_parts)
            if_index = bridge_to_if.get(bridge_port, bridge_port)
            if if_index in info.ports:
                fdb.setdefault(if_index, [])
                if mac not in fdb[if_index]:
                    fdb[if_index].append(mac)
        self._fdb = fdb
        arp_raw = await client.walk(IP_NET_TO_MEDIA_PHYS, max_repetitions=16)
        arp: dict[str, str] = {}
        for suffix, value in arp_raw.items():
            if isinstance(value, bytes) and len(value) == 6 and len(suffix) >= 5:
                arp[":".join(f"{b:02x}" for b in value)] = ".".join(str(x) for x in suffix[-4:])
        self._arp = arp
        shared = self.hass.data.setdefault(DOMAIN, {}).setdefault("arp", {})
        shared[self.host] = arp

    def _resolve_macs(self, macs: list[str]) -> list[dict[str, Any]]:
        """Attach HA device names and IPs to MAC addresses."""
        registry = dr.async_get(self.hass)
        arp_all: dict[str, str] = {}
        for table in self.hass.data.get(DOMAIN, {}).get("arp", {}).values():
            arp_all.update(table)
        result = []
        for mac in macs[:MAX_MACS_PER_PORT]:
            item: dict[str, Any] = {"m": mac}
            device = _device_for_mac(registry, mac)
            if device is not None:
                item["n"] = device.name_by_user or device.name
            if mac in arp_all:
                item["ip"] = arp_all[mac]
            vendor = _vendor(mac)
            if vendor:
                item["v"] = vendor
            result.append(item)
        return result

    def _fire(self, info: StaticInfo, index: int, event: str, **extra: Any) -> None:
        if not self._events:
            return
        self.hass.bus.async_fire(
            EVENT_PORT,
            {
                "device": self.config_entry.title,
                "host": self.host,
                "port": info.ports[index]["name"],
                "event": event,
                **extra,
            },
        )

    # ------------------------------------------------------------ polling

    async def _async_update_data(self) -> dict[str, Any]:
        now_mono = time.monotonic()
        try:
            if self.static is None or now_mono - self._static_ts > DISCOVERY_INTERVAL:
                self.static = await self._discover()
                self._static_ts = now_mono
            if now_mono - self._fdb_ts > FDB_INTERVAL:
                try:
                    await self._refresh_fdb(self.static)
                except SnmpError as err:
                    _LOGGER.debug("MAC table not readable on %s: %s", self.host, err)
                self._fdb_ts = now_mono
            return await self._poll(self.static)
        except SnmpTimeout as err:
            raise UpdateFailed(f"No SNMP response from {self.host}") from err
        except SnmpError as err:
            raise UpdateFailed(f"SNMP error from {self.host}: {err}") from err
        except OSError as err:
            raise UpdateFailed(f"Network error to {self.host}: {err}") from err

    async def _poll(self, info: StaticInfo) -> dict[str, Any]:
        client = self.client
        indexes = sorted(info.ports)

        oids: list[Oid] = [SYS_UPTIME]
        for index in indexes:
            oids += [
                IF_OPER_STATUS + (index,),
                IF_ADMIN_STATUS + (index,),
                IF_HIGH_SPEED + (index,),
                IF_HC_IN_OCTETS + (index,),
                IF_HC_OUT_OCTETS + (index,),
                IF_IN_ERRORS + (index,),
                IF_OUT_ERRORS + (index,),
                IF_LAST_CHANGE + (index,),
            ]
        eth = [i for i in indexes if info.ports[i]["kind"] == "eth"]
        if info.has_dot3:
            for i in eth:
                oids += [DOT3_DUPLEX + (i,), DOT3_FCS_ERRORS + (i,)]
        if info.has_poe:
            oids += [PETH_MAIN_POWER, PETH_MAIN_STATUS, PETH_MAIN_CONSUMPTION]
            oids += [PETH_PORT_DETECTION + (i,) for i in eth]
            if info.has_hp_poe_power:
                oids += [HP_POE_PORT_POWER_MW + (i,) for i in eth]
        if info.has_cpu:
            oids.append(HP_CPU)
        oids += [HR_PROCESSOR_LOAD + (i,) for i in info.hr_cpus]
        oids += [HP_SENSOR_STATUS + (i,) for i in info.sensors]

        # run batches with limited parallelism (keeps latency low over VPN)
        size = client.max_varbinds
        batches = [oids[i : i + size] for i in range(0, len(oids), size)]
        semaphore = asyncio.Semaphore(3)

        async def run(batch: list[Oid]) -> dict[Oid, Any]:
            async with semaphore:
                return await client.get(batch)

        values: dict[Oid, Any] = {}
        for part in await asyncio.gather(*(run(b) for b in batches)):
            values.update(part)
        if SYS_UPTIME not in values:
            raise SnmpError("sysUpTime missing")

        now = time.time()
        uptime_s = int(values[SYS_UPTIME]) / 100
        boot = now - uptime_s
        if self._boot_ts is None or abs(boot - self._boot_ts) > 120:
            self._boot_ts = boot

        lag_of: dict[int, str] = {}
        for lag_index, members in info.lag_members.items():
            for member in members:
                lag_of[member] = info.ports[lag_index]["name"]

        ports: list[dict[str, Any]] = []
        total_in = total_out = 0.0
        up_count = 0
        eth_count = 0
        poe_ports = 0
        for index in indexes:
            meta = info.ports[index]
            oper = values.get(IF_OPER_STATUS + (index,))
            admin = values.get(IF_ADMIN_STATUS + (index,))
            speed = values.get(IF_HIGH_SPEED + (index,), 0) or 0
            hc_in = values.get(IF_HC_IN_OCTETS + (index,))
            hc_out = values.get(IF_HC_OUT_OCTETS + (index,))
            rate_in = rate_out = 0.0
            if isinstance(hc_in, int) and isinstance(hc_out, int):
                prev = self._counters.get(index)
                if prev is not None:
                    elapsed = now - prev[0]
                    d_in = hc_in - prev[1]
                    d_out = hc_out - prev[2]
                    if elapsed > 0 and d_in >= 0 and d_out >= 0:
                        rate_in = d_in * 8 / elapsed
                        rate_out = d_out * 8 / elapsed
                self._counters[index] = (now, hc_in, hc_out)
            is_up = oper == 1
            port: dict[str, Any] = {
                "i": index,
                "n": meta["name"],
                "a": meta["alias"],
                "k": meta["kind"],
                "up": is_up,
                "adm": admin == 1,
                "spd": int(speed) if is_up else 0,
                "in": round(rate_in),
                "out": round(rate_out),
                "ie": int(values.get(IF_IN_ERRORS + (index,), 0) or 0),
                "oe": int(values.get(IF_OUT_ERRORS + (index,), 0) or 0),
            }
            # link since / flapping / error rate (health)
            last_change = values.get(IF_LAST_CHANGE + (index,))
            if isinstance(last_change, int) and last_change <= int(values[SYS_UPTIME]):
                port["ls"] = int(now - (int(values[SYS_UPTIME]) - last_change) / 100)
            if isinstance(oper, int):
                previous = self._prev_oper.get(index)
                flaps = self._flap_hist.setdefault(index, deque())
                if previous is not None and previous != oper:
                    flaps.append(now)
                    if meta["kind"] == "eth" and oper in (1, 2):
                        self._fire(info, index, "link_up" if oper == 1 else "link_down")
                self._prev_oper[index] = oper
                while flaps and now - flaps[0] > 3600:
                    flaps.popleft()
                port["flaps_h"] = len(flaps)
            if is_up and meta["kind"] == "eth":
                previous_speed = self._prev_speed.get(index)
                if previous_speed and speed and previous_speed != speed:
                    self._fire(info, index, "speed_change", old=previous_speed, new=int(speed))
                self._prev_speed[index] = int(speed)
            macs = self._fdb.get(index)
            if macs:
                port["mac_n"] = len(macs)
                if len(macs) <= MAX_MACS_PER_PORT:
                    port["mac"] = self._resolve_macs(macs)
            duplex = values.get(DOT3_DUPLEX + (index,))
            if duplex in (2, 3):
                port["dup"] = "half" if duplex == 2 else "full"
            fcs = values.get(DOT3_FCS_ERRORS + (index,))
            if isinstance(fcs, int):
                port["fcs"] = fcs
            err_total = port["ie"] + port["oe"] + (fcs if isinstance(fcs, int) else 0)
            hist = self._err_hist.setdefault(index, deque())
            if hist and err_total < hist[-1][1]:
                hist.clear()  # counter reset (reboot)
            hist.append((now, err_total))
            while len(hist) > 1 and now - hist[1][0] >= 3600:
                hist.popleft()
            if len(hist) > 1:
                port["err_h"] = err_total - hist[0][1]
            if index in info.pvid:
                port["vlan"] = info.pvid[index]
            if index in lag_of:
                port["lag"] = lag_of[index]
            if meta["kind"] == "lag":
                port["mem"] = [
                    info.ports[m]["name"] for m in info.lag_members.get(index, [])
                ]
            if index in info.neighbors:
                port["nb"] = info.neighbors[index]
            if meta["kind"] == "eth":
                eth_count += 1
                if is_up:
                    up_count += 1
                total_in += rate_in
                total_out += rate_out
                detection = values.get(PETH_PORT_DETECTION + (index,))
                if isinstance(detection, int):
                    state = PETH_DETECTION_STATES.get(detection, "unknown")
                    port["poe"] = state
                    if state == "delivering":
                        poe_ports += 1
                    milliwatt = values.get(HP_POE_PORT_POWER_MW + (index,))
                    if isinstance(milliwatt, int) and milliwatt > 0:
                        port["pw"] = round(milliwatt / 1000, 1)
            ports.append(port)

        poe: dict[str, Any] | None = None
        if info.has_poe and PETH_MAIN_POWER in values:
            poe = {
                "budget": int(values.get(PETH_MAIN_POWER, 0)),
                "used": int(values.get(PETH_MAIN_CONSUMPTION, 0)),
                "on": values.get(PETH_MAIN_STATUS) == 1,
                "ports": poe_ports,
            }

        sensors = []
        for index, descr in sorted(info.sensors.items()):
            status = values.get(HP_SENSOR_STATUS + (index,))
            sensors.append(
                {
                    "id": index,
                    "name": descr,
                    "status": HP_SENSOR_STATES.get(status, "unknown")
                    if isinstance(status, int)
                    else "unknown",
                }
            )

        cpu = values.get(HP_CPU)
        if not isinstance(cpu, int) and info.hr_cpus:
            loads = [
                values[HR_PROCESSOR_LOAD + (i,)]
                for i in info.hr_cpus
                if isinstance(values.get(HR_PROCESSOR_LOAD + (i,)), int)
            ]
            cpu = round(sum(loads) / len(loads)) if loads else None
        data: dict[str, Any] = {
            "system": {
                "name": info.name,
                "host": self.host,
                "model": info.model,
                "manufacturer": info.manufacturer,
                "firmware": info.firmware,
                "location": info.location,
                "descr": info.descr,
                "uptime": int(uptime_s),
                "boot_ts": int(self._boot_ts),
                "cpu": int(cpu) if isinstance(cpu, int) else None,
                "vlans": {str(k): v for k, v in sorted(info.vlans.items())},
            },
            "ports": ports,
            "poe": poe,
            "sensors": sensors,
            "totals": {
                "in": round(total_in),
                "out": round(total_out),
                "up": up_count,
                "total": eth_count,
            },
            "ts": int(now),
        }
        data["health"] = evaluate(data)
        return data
