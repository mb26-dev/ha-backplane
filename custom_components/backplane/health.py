"""Switch health evaluation and report rendering for Backplane."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

_PENALTY = {CRITICAL: 25, WARNING: 10, INFO: 2}
_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}

# thresholds
ERRORS_WARN_PER_H = 10
ERRORS_CRIT_PER_H = 500
FLAPS_WARN_PER_H = 3
POE_WARN = 0.80
POE_CRIT = 0.95
CPU_WARN = 80
REBOOT_INFO_S = 24 * 3600
UTIL_INFO_PCT = 80
UTIL_WARN_PCT = 95
BCAST_WARN_PPS = 1000
BCAST_CRIT_PPS = 5000
STP_TC_WARN_PER_H = 3


def _finding(level: str, code: str, message: str, port: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"level": level, "code": code, "msg": message}
    if port is not None:
        item["port"] = port
    return item


def evaluate(data: dict[str, Any]) -> dict[str, Any]:
    """Return {'score', 'grade', 'findings'} for one device's coordinator data."""
    findings: list[dict[str, Any]] = []
    system = data.get("system", {})

    for sensor in data.get("sensors", []):
        if sensor["status"] == "bad":
            findings.append(_finding(CRITICAL, "hw_bad", f"{sensor['name']} reports a failure"))
        elif sensor["status"] == "warning":
            findings.append(_finding(WARNING, "hw_warn", f"{sensor['name']} reports a warning"))

    poe = data.get("poe")
    if poe and poe.get("budget"):
        ratio = poe["used"] / poe["budget"]
        if ratio >= POE_CRIT:
            findings.append(_finding(CRITICAL, "poe_budget", f"PoE budget almost exhausted ({poe['used']}/{poe['budget']} W)"))
        elif ratio >= POE_WARN:
            findings.append(_finding(WARNING, "poe_budget", f"PoE budget above 80 % ({poe['used']}/{poe['budget']} W)"))
    if poe and not poe.get("on", True):
        findings.append(_finding(WARNING, "poe_off", "PoE power supply is off"))

    cpu = system.get("cpu")
    if isinstance(cpu, (int, float)) and cpu >= CPU_WARN:
        findings.append(_finding(WARNING, "cpu", f"High CPU load ({cpu} %)"))

    uptime = system.get("uptime")
    if isinstance(uptime, (int, float)) and uptime < REBOOT_INFO_S:
        hours = max(1, int(uptime // 3600))
        findings.append(_finding(INFO, "reboot", f"Rebooted {hours} h ago"))

    stp = data.get("stp") or {}
    tc_h = stp.get("tc_h")
    if isinstance(tc_h, int) and tc_h >= STP_TC_WARN_PER_H:
        findings.append(_finding(WARNING, "stp_unstable", f"Spanning tree unstable ({tc_h} topology changes in 1 h) - possible loop or flapping link"))
    elif isinstance(tc_h, int) and tc_h > 0:
        findings.append(_finding(INFO, "stp_change", "Spanning tree topology changed in the last hour"))

    ports = data.get("ports", [])
    by_name = {p["n"]: p for p in ports}
    for port in ports:
        name = port["n"]
        util = port.get("u")
        if isinstance(util, (int, float)):
            if util >= UTIL_WARN_PCT:
                findings.append(_finding(WARNING, "port_saturated", f"Port {name} saturated ({util:.0f} % of link speed)", name))
            elif util >= UTIL_INFO_PCT:
                findings.append(_finding(INFO, "port_busy", f"Port {name} busy ({util:.0f} % of link speed)", name))
        bcast = port.get("bc")
        if isinstance(bcast, int):
            if bcast >= BCAST_CRIT_PPS:
                findings.append(_finding(CRITICAL, "broadcast_storm", f"Port {name}: broadcast storm ({bcast} pkt/s) - check for a loop", name))
            elif bcast >= BCAST_WARN_PPS:
                findings.append(_finding(WARNING, "broadcast_high", f"Port {name}: high broadcast rate ({bcast} pkt/s)", name))
        if port["k"] == "lag":
            members = [by_name[m] for m in port.get("mem", []) if m in by_name]
            down = [m["n"] for m in members if not m["up"]]
            if members and down and len(down) < len(members):
                findings.append(_finding(WARNING, "lag_degraded", f"Trunk {name} degraded - member {', '.join(down)} down", name))
            elif members and len(down) == len(members):
                findings.append(_finding(CRITICAL, "lag_down", f"Trunk {name} is down", name))
            continue
        errors = port.get("err_h")
        if isinstance(errors, int) and errors > 0:
            if errors >= ERRORS_CRIT_PER_H:
                findings.append(_finding(CRITICAL, "errors", f"Port {name}: {errors} errors in the last hour", name))
            elif errors >= ERRORS_WARN_PER_H:
                findings.append(_finding(WARNING, "errors", f"Port {name}: {errors} errors in the last hour", name))
        flaps = port.get("flaps_h", 0)
        if flaps >= FLAPS_WARN_PER_H:
            findings.append(_finding(WARNING, "flapping", f"Port {name} flapping ({flaps} link changes in 1 h)", name))
        if port["up"] and port.get("dup") == "half":
            findings.append(_finding(WARNING, "half_duplex", f"Port {name} runs half duplex", name))
        if port["up"] and 0 < port.get("spd", 0) <= 10:
            findings.append(_finding(INFO, "slow_link", f"Port {name} linked at 10 Mbit", name))

    findings.sort(key=lambda f: (_ORDER[f["level"]], f.get("port", "")))
    score = 100 - sum(_PENALTY[f["level"]] for f in findings)
    score = max(0, min(100, score))
    if any(f["level"] == CRITICAL for f in findings):
        grade = "critical"
    elif any(f["level"] == WARNING for f in findings):
        grade = "warning"
    else:
        grade = "healthy"
    return {"score": score, "grade": grade, "findings": findings}


# ---------------------------------------------------------------- report

_LEVEL_COLOR = {CRITICAL: "#ff5252", WARNING: "#ffb300", INFO: "#40c4ff"}
_GRADE_COLOR = {"healthy": "#69f0ae", "warning": "#ffb300", "critical": "#ff5252"}


def _fmt_bytes(value: float) -> str:
    for unit, size in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6)):
        if value >= size:
            return f"{value / size:.2f} {unit}" if unit != "MB" else f"{value / size:.0f} {unit}"
    return f"{value / 1e3:.0f} kB"


def _fmt_rate(bps: float) -> str:
    for unit, div in (("Gb/s", 1e9), ("Mb/s", 1e6), ("kb/s", 1e3)):
        if bps >= div:
            return f"{bps / div:.1f} {unit}"
    return f"{bps:.0f} b/s"


def _fmt_uptime(seconds: int) -> str:
    days, rest = divmod(int(seconds), 86400)
    return f"{days}d {rest // 3600}h" if days else f"{rest // 3600}h {(rest % 3600) // 60}m"


def render_report(devices: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (html, text). Email-safe HTML: tables only, rgba colours, no flexbox."""
    esc = html.escape
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    worst = "healthy"
    for dev in devices:
        if dev["health"]["grade"] == "critical":
            worst = "critical"
        elif dev["health"]["grade"] == "warning" and worst != "critical":
            worst = "warning"

    text_lines = [f"Backplane Switch Health Report - {now}", ""]
    blocks = []
    for dev in devices:
        sysd = dev["system"]
        health = dev["health"]
        totals = dev["totals"]
        color = _GRADE_COLOR[health["grade"]]
        text_lines.append(
            f"{dev['title']} ({sysd['host']}): score {health['score']} - {health['grade']} - "
            f"ports {totals['up']}/{totals['total']} - up {_fmt_uptime(sysd['uptime'])}"
        )
        rows = []
        for finding in health["findings"]:
            fcol = _LEVEL_COLOR[finding["level"]]
            rows.append(
                f'<tr><td style="padding:4px 8px;width:80px;"><span style="color:{fcol};font-weight:bold;">'
                f'{esc(finding["level"].upper())}</span></td><td style="padding:4px 8px;color:#e0e0e0;">{esc(finding["msg"])}</td></tr>'
            )
            text_lines.append(f"  [{finding['level']}] {finding['msg']}")
        if not rows:
            rows.append('<tr><td colspan="2" style="padding:4px 8px;color:#69f0ae;">No findings - all ports and hardware healthy.</td></tr>')
            text_lines.append("  no findings")
        poe = dev.get("poe")
        poe_cell = f"{poe['used']} / {poe['budget']} W" if poe else "-"
        cpu = sysd.get("cpu")
        blocks.append(
            f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 16px 0;background:rgba(255,255,255,0.05);border:1px solid rgba(255,215,0,0.55);border-radius:12px;">
<tr><td style="padding:12px 14px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td style="font-size:17px;font-weight:bold;color:#ffd700;">{esc(dev['title'])}</td>
    <td align="right"><span style="display:inline-block;padding:3px 10px;border-radius:12px;border:1px solid {color};color:{color};font-weight:bold;font-size:13px;">{health['score']} &middot; {esc(health['grade'].upper())}</span></td>
  </tr>
  <tr><td colspan="2" style="font-size:12px;color:#9e9e9e;padding-top:2px;">{esc(sysd.get('model') or '')} &middot; {esc(sysd.get('firmware') or '')} &middot; {esc(sysd['host'])}</td></tr>
  </table>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px;font-size:12px;color:#bdbdbd;">
  <tr>
    <td>Uptime<br><b style="color:#ffd700;">{_fmt_uptime(sysd['uptime'])}</b></td>
    <td>Ports up<br><b style="color:#ffd700;">{totals['up']}/{totals['total']}</b></td>
    <td>Traffic<br><b style="color:#ffd700;">{_fmt_rate(totals['in'])}</b></td>
    <td>Today<br><b style="color:#ffd700;">{_fmt_bytes(totals.get('day_in', 0) + totals.get('day_out', 0))}</b></td>
    <td>CPU<br><b style="color:#ffd700;">{cpu if cpu is not None else '-'}{' %' if cpu is not None else ''}</b></td>
    <td>PoE<br><b style="color:#ffd700;">{poe_cell}</b></td>
  </tr>
  </table>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px;font-size:13px;border-top:1px solid rgba(255,215,0,0.2);">
  {''.join(rows)}
  </table>
</td></tr></table>"""
        )
        text_lines.append("")

    wcol = _GRADE_COLOR[worst]
    html_doc = f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#1a1a1a;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">
<tr><td align="center" style="padding:16px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;font-family:Arial,Helvetica,sans-serif;">
<tr><td style="padding:16px;border:2px solid #ffd700;border-radius:14px;background:#1a1a1a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
  <tr>
    <td style="font-size:20px;font-weight:bold;color:#ffd700;">Switch Health Report</td>
    <td align="right"><span style="display:inline-block;padding:4px 12px;border-radius:14px;background:rgba(255,215,0,0.08);border:1px solid {wcol};color:{wcol};font-weight:bold;font-size:13px;">{esc(worst.upper())}</span></td>
  </tr>
  <tr><td colspan="2" style="font-size:12px;color:#9e9e9e;">{now} &middot; {len(devices)} device(s) &middot; Backplane</td></tr>
  </table>
  {''.join(blocks)}
</td></tr></table>
</td></tr></table></body></html>"""
    return html_doc, "\n".join(text_lines)
