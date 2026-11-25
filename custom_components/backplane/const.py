"""Constants for Backplane."""

from __future__ import annotations

DOMAIN = "backplane"
VERSION = "0.4.0"

CONF_COMMUNITY = "community"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_PORT_FILTER = "port_filter"
CONF_PORT_EVENTS = "port_events"
CONF_SNMP_VERSION = "snmp_version"
CONF_V3_USER = "v3_user"
CONF_AUTH_PROTOCOL = "auth_protocol"
CONF_AUTH_PASSWORD = "auth_password"
CONF_PRIV_PROTOCOL = "priv_protocol"
CONF_PRIV_PASSWORD = "priv_password"

EVENT_PORT = "backplane_port_event"
FDB_INTERVAL = 120
MAX_MACS_PER_PORT = 8

DEFAULT_PORT = 161
DEFAULT_COMMUNITY = "public"
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 600

# Interface names, trunks, LLDP neighbours, VLANs are re-read every 10 minutes
DISCOVERY_INTERVAL = 600

URL_BASE = "/backplane_static"
CARD_FILENAME = "backplane-card.js"

# ---- MIB-2 / IF-MIB
SYS_DESCR = (1, 3, 6, 1, 2, 1, 1, 1, 0)
SYS_OBJECT_ID = (1, 3, 6, 1, 2, 1, 1, 2, 0)
SYS_UPTIME = (1, 3, 6, 1, 2, 1, 1, 3, 0)
SYS_CONTACT = (1, 3, 6, 1, 2, 1, 1, 4, 0)
SYS_NAME = (1, 3, 6, 1, 2, 1, 1, 5, 0)
SYS_LOCATION = (1, 3, 6, 1, 2, 1, 1, 6, 0)

IF_TYPE = (1, 3, 6, 1, 2, 1, 2, 2, 1, 3)
IF_ADMIN_STATUS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 7)
IF_OPER_STATUS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 8)
IF_IN_ERRORS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 14)
IF_OUT_ERRORS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 20)
IF_LAST_CHANGE = (1, 3, 6, 1, 2, 1, 2, 2, 1, 9)
# EtherLike-MIB
DOT3_FCS_ERRORS = (1, 3, 6, 1, 2, 1, 10, 7, 2, 1, 3)
DOT3_DUPLEX = (1, 3, 6, 1, 2, 1, 10, 7, 2, 1, 19)
IF_NAME = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 1)
IF_HC_IN_OCTETS = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 6)
IF_HC_OUT_OCTETS = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 10)
IF_HIGH_SPEED = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 15)
IF_ALIAS = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 18)
IF_STACK_STATUS = (1, 3, 6, 1, 2, 1, 31, 1, 2, 1, 3)

IFTYPE_ETHERNET = {6, 62, 69, 117}

# Linux/OpenWrt report bridges, Wi-Fi, VPN and VLAN sub-interfaces as ethernet.
# These are never front-panel ports (auto mode).
AUTO_EXCLUDE = (
    r"^(lo|br-.*|br\d+|bridge.*|phy\d+-.*|wlan.*|mon\d*|tailscale.*|wg\d*|tun\d*|tap\d*"
    r"|veth.*|docker.*|ifb.*|sit\d*|gre.*|ip6tnl.*|pppoe-.*|dummy.*|bat\d*|.*\..*)$"
)

# ---- HOST-RESOURCES-MIB (Linux / OpenWrt CPU)
HR_PROCESSOR_LOAD = (1, 3, 6, 1, 2, 1, 25, 3, 3, 1, 2)
IFTYPE_LAG = 161

# ---- Q-BRIDGE-MIB
DOT1Q_VLAN_NAME = (1, 3, 6, 1, 2, 1, 17, 7, 1, 4, 3, 1, 1)
DOT1Q_PVID = (1, 3, 6, 1, 2, 1, 17, 7, 1, 4, 5, 1, 1)

# ---- BRIDGE-MIB / Q-BRIDGE-MIB forwarding database (MAC table)
DOT1D_BASE_PORT_IFINDEX = (1, 3, 6, 1, 2, 1, 17, 1, 4, 1, 2)
DOT1Q_TP_FDB_PORT = (1, 3, 6, 1, 2, 1, 17, 7, 1, 2, 2, 1, 2)
DOT1D_TP_FDB_PORT = (1, 3, 6, 1, 2, 1, 17, 4, 3, 1, 2)
# IP-MIB ARP table (routers): ifIndex.a.b.c.d -> MAC
IP_NET_TO_MEDIA_PHYS = (1, 3, 6, 1, 2, 1, 4, 22, 1, 2)

# ---- LLDP-MIB
LLDP_LOC_PORT_ID = (1, 0, 8802, 1, 1, 2, 1, 3, 7, 1, 3)
LLDP_REM_PORT_ID = (1, 0, 8802, 1, 1, 2, 1, 4, 1, 1, 7)
LLDP_REM_PORT_DESC = (1, 0, 8802, 1, 1, 2, 1, 4, 1, 1, 8)
LLDP_REM_SYS_NAME = (1, 0, 8802, 1, 1, 2, 1, 4, 1, 1, 9)
LLDP_REM_SYS_DESC = (1, 0, 8802, 1, 1, 2, 1, 4, 1, 1, 10)

# ---- POWER-ETHERNET-MIB (RFC 3621)
PETH_PORT_DETECTION = (1, 3, 6, 1, 2, 1, 105, 1, 1, 1, 6, 1)
PETH_MAIN_POWER = (1, 3, 6, 1, 2, 1, 105, 1, 3, 1, 1, 2, 1)
PETH_MAIN_STATUS = (1, 3, 6, 1, 2, 1, 105, 1, 3, 1, 1, 3, 1)
PETH_MAIN_CONSUMPTION = (1, 3, 6, 1, 2, 1, 105, 1, 3, 1, 1, 4, 1)

PETH_DETECTION_STATES = {
    1: "disabled",
    2: "searching",
    3: "delivering",
    4: "fault",
    5: "test",
    6: "other_fault",
}

# ---- HP / Aruba ProCurve (enterprise 11)
HP_ENTERPRISE = (1, 3, 6, 1, 4, 1, 11)
HP_POE_PORT_POWER_MW = (1, 3, 6, 1, 4, 1, 11, 2, 14, 11, 1, 9, 1, 1, 1, 3, 1)
HP_CPU = (1, 3, 6, 1, 4, 1, 11, 2, 14, 11, 5, 1, 9, 6, 1, 0)
HP_SENSOR_STATUS = (1, 3, 6, 1, 4, 1, 11, 2, 14, 11, 1, 2, 6, 1, 4)
HP_SENSOR_DESCR = (1, 3, 6, 1, 4, 1, 11, 2, 14, 11, 1, 2, 6, 1, 7)

HP_SENSOR_STATES = {
    1: "unknown",
    2: "bad",
    3: "warning",
    4: "good",
    5: "not_present",
}
