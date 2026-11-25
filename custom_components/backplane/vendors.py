"""Vendor detection from sysObjectID (IANA enterprise number) and sysDescr."""
from __future__ import annotations

import re

# IANA private enterprise numbers -> display name
ENTERPRISES: dict[int, str] = {
    9: "Cisco",
    11: "HPE Aruba",
    43: "3Com",
    171: "D-Link",
    207: "Allied Telesis",
    248: "Hirschmann",
    674: "Dell",
    890: "Zyxel",
    1588: "Brocade",
    1916: "Extreme Networks",
    1991: "Brocade",
    2011: "Huawei",
    2636: "Juniper",
    3902: "ZTE",
    3955: "Linksys",
    4329: "Siemens",
    4413: "Ubiquiti",
    4526: "Netgear",
    6027: "Dell",
    6486: "Alcatel-Lucent",
    6574: "Synology",
    8691: "Moxa",
    10002: "Ubiquiti",
    11863: "TP-Link",
    12356: "Fortinet",
    14823: "Aruba",
    14988: "MikroTik",
    24681: "QNAP",
    25053: "Ruckus",
    25506: "HPE Comware",
    29671: "Cisco Meraki",
    30065: "Arista",
    41112: "Ubiquiti",
    47196: "HPE Aruba",
}

# sysDescr keywords, checked first (more specific than the enterprise number)
DESCR_HINTS: list[tuple[str, str]] = [
    (r"\bOpenWrt\b", "OpenWrt"),
    (r"\bRouterOS\b", "MikroTik"),
    (r"\bpfSense\b", "pfSense"),
    (r"\bOPNsense\b", "OPNsense"),
    (r"\bUniFi\b|\bEdgeSwitch\b|\bUSW-", "Ubiquiti"),
    (r"\bMeraki\b", "Cisco Meraki"),
    (r"\bAruba\b|\bArubaOS\b", "HPE Aruba"),
    (r"\bProCurve\b|^HP\s+J\d{4}", "HPE Aruba"),
    (r"\bComware\b|\bH3C\b", "HPE Comware"),
    (r"\bCisco\b|\bIOS\b", "Cisco"),
    (r"\bJUNOS\b|\bJuniper\b", "Juniper"),
    (r"\bNetgear\b|^GS\d{3}(?!\d)|^XS\d{3}(?!\d)|^M4\d{3}", "Netgear"),
    (r"\bTP-?Link\b|\bJetStream\b|\bOmada\b|^T\d{4}", "TP-Link"),
    (r"\bD-Link\b|^DGS-|^DES-|^DXS-", "D-Link"),
    (r"\bZyxel\b|^GS\d{4}|^XGS\d{4}|^XS\d{4}", "Zyxel"),
    (r"\bQNAP\b|^QSW-", "QNAP"),
    (r"\bDell\b|\bPowerConnect\b|\bOS10\b", "Dell"),
    (r"\bHuawei\b|\bVRP\b", "Huawei"),
    (r"\bArista\b|\bEOS\b", "Arista"),
    (r"\bFortiSwitch\b|\bFortiGate\b|\bFortinet\b", "Fortinet"),
    (r"\bRuckus\b|\bICX\d", "Ruckus"),
    (r"\bExtreme\b|\bEXOS\b", "Extreme Networks"),
    (r"\bBrocade\b|\bFastIron\b", "Brocade"),
    (r"\bAllied\s*Telesis\b|\bAlliedWare\b", "Allied Telesis"),
    (r"\bLinksys\b", "Linksys"),
    (r"\bCudy\b", "Cudy"),
    (r"\bGL\.iNet\b|\bGL-[A-Z]", "GL.iNet"),
    (r"\bSynology\b", "Synology"),
]


def detect_vendor(object_id: object, descr: str) -> str:
    """Return a display name for the device vendor, or '' if unknown."""
    for pattern, name in DESCR_HINTS:
        if re.search(pattern, descr or "", re.IGNORECASE if pattern[0] != "^" else 0):
            return name
    if isinstance(object_id, tuple) and len(object_id) > 6 and object_id[:6] == (1, 3, 6, 1, 4, 1):
        return ENTERPRISES.get(object_id[6], "")
    return ""
