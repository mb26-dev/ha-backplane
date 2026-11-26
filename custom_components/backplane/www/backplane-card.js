/*
 * Backplane card - live switch front panel for Home Assistant.
 * Served by the Backplane integration (custom_components/backplane).
 */
const BP_VERSION = "0.7.1";

const SPEED_COLORS = [
  [10000, "#00e5ff"],
  [1000, "#ffd700"],
  [100, "#ff9f1a"],
  [1, "#ff5252"],
];
const LAG_COLORS = ["#b388ff", "#69f0ae", "#ff80ab", "#40c4ff"];
const IN_COLOR = "#ffd700";
const GRADE_COLORS = { healthy: "#69f0ae", warning: "#ffb300", critical: "#ff5252" };
const LEVEL_COLORS = { critical: "#ff5252", warning: "#ffb300", info: "#40c4ff" };

const macName = (m) => m.n || (m.v && m.v !== "random / virtual" ? m.v : "");
const portLabel = (p) =>
  p.a || (p.nb && p.nb.name) || (p.mac && p.mac.length <= 3 ? p.mac.map(macName).find(Boolean) : "") || "";

const lagPorts = (item, hass) => {
  const state = hass && hass.states[item.entity];
  return ((state && state.attributes.ports) || []).filter((p) => p.k === "lag");
};

const fmtSince = (ts) => {
  if (!ts) return "-";
  return fmtUptime(Math.max(0, Date.now() / 1000 - ts));
};
const OUT_COLOR = "#00e5ff";

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const speedColor = (mbit) => {
  for (const [limit, color] of SPEED_COLORS) if (mbit >= limit) return color;
  return "#3a3a3a";
};

const speedLabel = (mbit) => {
  if (!mbit) return "down";
  if (mbit >= 1000) return `${mbit / 1000 % 1 ? (mbit / 1000).toFixed(1) : mbit / 1000} Gbit`;
  return `${mbit} Mbit`;
};

const fmtRate = (bps) => {
  const n = Number(bps);
  if (!Number.isFinite(n) || n < 1) return "0 b/s";
  const units = ["b/s", "kb/s", "Mb/s", "Gb/s"];
  let value = n;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[unit]}`;
};

// port data comes from the switch over SNMP: numeric fields are forced to numbers, the index to an integer
const PORT_NUMERIC = ["in", "out", "spd", "pw", "ie", "oe", "bc", "util"];
const normPort = (p) => {
  const out = { ...p, i: parseInt(p.i, 10) || 0 };
  for (const k of PORT_NUMERIC) if (k in out && out[k] != null) { const v = Number(out[k]); out[k] = Number.isFinite(v) ? v : 0; }
  return out;
};

const fmtBytes = (bytes) => {
  const b = Number(bytes) || 0;
  if (b >= 1e12) return `${(b / 1e12).toFixed(2)} TB`;
  if (b >= 1e9) return `${(b / 1e9).toFixed(2)} GB`;
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  if (b >= 1e3) return `${(b / 1e3).toFixed(0)} kB`;
  return `${b} B`;
};

const fmtUptime = (seconds) => {
  if (seconds == null) return "-";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};

const blinkDuration = (bps) => {
  if (!bps || bps < 2000) return null;
  const d = 1.5 - 0.22 * Math.log10(bps);
  return Math.max(0.09, Math.min(1.2, d)).toFixed(2);
};

const STYLE = `
  :host { display: block; }
  ha-card {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,215,0,0.55);
    box-shadow: 0px 0px 12px 2px rgba(255,215,0,1);
    border-radius: 16px;
    padding: 12px 14px 14px;
    color: var(--primary-text-color, #eee);
    font-family: var(--primary-font-family, sans-serif);
    overflow: hidden;
  }
  .sw + .sw { margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,215,0,0.25); }
  .hdr { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; justify-content: space-between; }
  .ttl { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1 1 200px; }
  .hlogo { height: 22px; width: auto; max-width: 70px; object-fit: contain; flex: 0 0 auto; }
  .ttl ha-icon { flex: 0 0 22px; --mdc-icon-size: 22px; color: #ffd700; }
  .name { font-size: 16px; font-weight: 600; color: #ffd700; letter-spacing: .3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sub { font-size: 11px; opacity: .7; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .state { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 9px; background: #69f0ae; box-shadow: 0 0 8px #69f0ae; }
  .state.off { background: #ff5252; box-shadow: 0 0 8px #ff5252; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
  .chip { font-size: 11px; padding: 3px 8px; border-radius: 10px; background: rgba(255,215,0,0.08); border: 1px solid rgba(255,215,0,0.25); white-space: nowrap; }
  .chip b { color: #ffd700; font-weight: 600; }
  .chip.bad { background: rgba(255,82,82,0.15); border-color: #ff5252; color: #ff8a80; }
  .panel { margin-top: 10px; }
  .panel svg { width: 100%; max-width: 1120px; height: auto; display: block; margin: 0 auto; }
  .sparkwrap { position: relative; }
  .sparkwrap .sl { position: absolute; font-size: 10px; opacity: .6; }
  .sparkwrap .tl { top: 0; left: 4px; }
  .sparkwrap .br { bottom: 2px; right: 4px; }
  .port { cursor: pointer; }
  .port:hover .body { stroke-width: 2.2; }
  .act.on { animation: bp-blink var(--d, .6s) steps(2, jump-none) infinite; }
  @keyframes bp-blink { 0% { opacity: 1; } 50% { opacity: .12; } 100% { opacity: 1; } }
  @keyframes bp-flow { to { stroke-dashoffset: -32; } }
  .topo { margin-bottom: 14px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,215,0,0.25); }
  .devs { display: grid; gap: 3px; margin-top: 8px; }
  .poebolt { filter: drop-shadow(0 0 3px #ffb300); }
  .sel .body { stroke: #ffffff !important; stroke-width: 2.6; }
  .row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
  .box { flex: 1 1 220px; min-width: 0; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,215,0,0.18); border-radius: 12px; padding: 8px 10px 10px; }
  .box h4 { margin: 0 0 6px; font-size: 11px; font-weight: 600; letter-spacing: .6px; text-transform: uppercase; color: rgba(255,215,0,0.85); display: flex; justify-content: space-between; gap: 8px; }
  .box h4 span { text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--primary-text-color, #eee); opacity: .85; white-space: nowrap; }
  .spark { width: 100%; height: 64px; display: block; }
  .bar { height: 10px; border-radius: 6px; background: rgba(255,255,255,0.08); overflow: hidden; }
  .bar i { display: block; height: 100%; border-radius: 6px; background: linear-gradient(90deg, #ffb300, #ffd700); box-shadow: 0 0 8px rgba(255,215,0,.6); }
  .muted { font-size: 11px; opacity: .65; margin-top: 6px; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .lg { font-size: 11px; display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; border-radius: 10px; background: rgba(255,255,255,0.05); }
  .lg i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; flex: 0 0 8px; }
  .list { display: grid; gap: 4px; }
  .li { display: grid; grid-template-columns: auto minmax(0,1fr) auto; gap: 8px; font-size: 12px; align-items: center; cursor: pointer; padding: 3px 4px; border-radius: 6px; }
  .li:hover { background: rgba(255,215,0,0.08); }
  .li .p { color: #ffd700; font-weight: 600; min-width: 34px; }
  .li .n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .li .r { opacity: .7; font-size: 11px; white-space: nowrap; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 6px 10px; }
  .kv { min-width: 0; }
  .kv .k { font-size: 10px; text-transform: uppercase; letter-spacing: .5px; opacity: .6; }
  .kv .v { font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .close { cursor: pointer; opacity: .7; font-size: 11px; }
  .warn { margin-top: 8px; font-size: 12px; color: #ff8a80; }
  .hb { display: grid; grid-template-columns: 64px minmax(0,1fr); gap: 10px; align-items: start; }
  .fd { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 6px; font-size: 12px; padding: 2px 0; align-items: baseline; }
  .fd i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: 0 0 8px; }
  .fd span { overflow: hidden; text-overflow: ellipsis; }
  .unavail { padding: 16px; text-align: center; opacity: .7; }
`;

const fmtAgo = (seconds) => {
  const s = Math.max(0, Math.round(seconds));
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
};

function wordmark(name, x, y, maxW) {
  const label = String(name || "").toUpperCase();
  if (!label) return "";
  const size = Math.max(9, Math.min(15, (maxW - 18) / (label.length * 0.74)));
  const w = Math.min(maxW, Math.round(label.length * size * 0.74 + 18));
  const h = Math.round(size + 12);
  return `<g class="wordmark">
    <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${h / 2}" fill="rgba(255,215,0,0.07)" stroke="rgba(255,215,0,0.55)" stroke-width="1"/>
    <text x="${x + w / 2}" y="${y + h / 2 + size * 0.36}" text-anchor="middle" fill="#ffd700" font-size="${size.toFixed(1)}" font-weight="800" letter-spacing="1.2">${esc(label)}</text>
  </g>`;
}

class BackplaneCard extends HTMLElement {
  constructor() {
    super();
    this._selected = {};
    this._history = {};
    this._seeded = {};
    this._portHistory = {};
    this._signature = "";
    this._narrow = false;
  }

  connectedCallback() {
    if (!this._resize && window.ResizeObserver) {
      this._resize = new ResizeObserver((entries) => {
        const width = entries[0].contentRect.width;
        const narrow = width > 0 && width < 620;
        if (narrow !== this._narrow) {
          this._narrow = narrow;
          this._render();
        }
      });
    }
    if (this._resize) this._resize.observe(this);
  }

  disconnectedCallback() {
    if (this._resize) this._resize.disconnect();
  }

  static getConfigElement() {
    return document.createElement("backplane-card-editor");
  }

  static getStubConfig(hass) {
    const found = Object.keys(hass.states).filter(
      (id) => id.startsWith("sensor.") && hass.states[id].attributes.backplane === true,
    );
    return { entities: found.slice(0, 2) };
  }

  setConfig(config) {
    if (!config || (!config.entity && !config.entities)) {
      throw new Error("Backplane: set 'entity' or 'entities' (sensor.*_backplane)");
    }
    const list = config.entities || [config.entity];
    this._items = list.map((item) => (typeof item === "string" ? { entity: item } : item));
    this._config = config;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    }
    this._signature = "";
    if (this._hass) this.hass = this._hass;
  }

  getCardSize() {
    return 6 * (this._items ? this._items.length : 1);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._items) return;
    const signature = this._items
      .map((item) => {
        const state = hass.states[item.entity];
        return state ? `${state.last_updated}` : "x";
      })
      .join("|");
    if (signature === this._signature) return;
    this._signature = signature;
    for (const item of this._items) {
      this._record(item.entity);
      this._seed(item.entity);
    }
    this._render();
  }

  // ---------------------------------------------------------------- history

  _record(entityId) {
    const state = this._hass.states[entityId];
    const attrs = state && state.attributes;
    if (!attrs || !attrs.totals || !attrs.ts) return;
    const hist = (this._history[entityId] ||= { in: [], out: [] });
    const t = attrs.ts * 1000;
    const last = hist.in[hist.in.length - 1];
    if (last && last[0] >= t) return;
    hist.in.push([t, attrs.totals.in]);
    hist.out.push([t, attrs.totals.out]);
    this._trim(hist);
    const perPort = (this._portHistory[entityId] ||= {});
    for (const port of attrs.ports || []) {
      const ph = (perPort[port.i] ||= { in: [], out: [] });
      ph.in.push([t, port.in]);
      ph.out.push([t, port.out]);
      this._trim(ph);
    }
  }

  _trim(hist) {
    const cutoff = Date.now() - 3600 * 1000;
    for (const key of ["in", "out"]) {
      hist[key] = hist[key].filter((point) => point[0] >= cutoff);
    }
  }

  async _seed(entityId) {
    if (this._seeded[entityId] || !this._hass.callWS) return;
    this._seeded[entityId] = true;
    const base = entityId.replace(/_backplane$/, "");
    const ids = [`${base}_traffic_in`, `${base}_traffic_out`];
    if (!ids.every((id) => this._hass.states[id])) return;
    try {
      const start = new Date(Date.now() - 3600 * 1000).toISOString();
      const result = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: start,
        entity_ids: ids,
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      });
      const parse = (rows) =>
        (rows || [])
          .map((row) => {
            const value = parseFloat(row.s ?? row.state);
            const ts = row.lu ?? (row.last_updated ? Date.parse(row.last_updated) / 1000 : null) ?? row.lc;
            return Number.isFinite(value) && ts ? [ts * 1000, value * 1e6] : null;
          })
          .filter(Boolean);
      const hist = (this._history[entityId] ||= { in: [], out: [] });
      const seededIn = parse(result[ids[0]]);
      const seededOut = parse(result[ids[1]]);
      const firstLive = hist.in.length ? hist.in[0][0] : Infinity;
      hist.in = seededIn.filter((p) => p[0] < firstLive).concat(hist.in);
      hist.out = seededOut.filter((p) => p[0] < firstLive).concat(hist.out);
      this._trim(hist);
      this._render();
    } catch (err) {
      // history is a nice-to-have; live samples keep filling the chart
    }
  }

  // ---------------------------------------------------------------- events

  _onClick(ev) {
    const target = ev.composedPath().find((el) => el.dataset && (el.dataset.port || el.dataset.close));
    if (!target) return;
    const entity = target.dataset.entity;
    if (target.dataset.close) {
      delete this._selected[entity];
    } else {
      const port = Number(target.dataset.port);
      this._selected[entity] = this._selected[entity] === port ? undefined : port;
    }
    this._render();
  }

  // ---------------------------------------------------------------- render

  _render() {
    if (!this.shadowRoot || !this._hass) return;
    const sections = this._items.map((item) => this._renderSwitch(item)).join("");
    const topo = this._config.topology === false ? "" : this._renderTopology();
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${topo}${sections}</ha-card>`;
  }

  _deviceName(item) {
    const state = this._hass.states[item.entity];
    const sys = state && state.attributes.system;
    return item.name || (sys && sys.name) || item.entity;
  }

  _renderTopology() {
    if (this._items.length < 2) return "";
    const nodes = this._items.map((item) => {
      const state = this._hass.states[item.entity];
      const attrs = (state && state.attributes) || {};
      const aliases = [item.name, attrs.system && attrs.system.name]
        .filter(Boolean)
        .map((n) => String(n).toLowerCase());
      return { item, attrs, name: this._deviceName(item), aliases, up: state && state.state !== "unavailable" };
    });
    const links = [];
    const seen = new Set();
    nodes.forEach((node, a) => {
      for (const port of node.attrs.ports || []) {
        if (!port.nb || !port.nb.name) continue;
        const b = nodes.findIndex((other, idx) => idx !== a && other.aliases.includes(String(port.nb.name).toLowerCase()));
        if (b < 0) continue;
        const key = [Math.min(a, b), Math.max(a, b)].join("-");
        if (seen.has(key)) continue;
        seen.add(key);
        links.push({ a, b, pa: port.n, pb: port.nb.port || "?", spd: port.spd, bps: Math.max(port.in, port.out), up: port.up });
      }
    });
    if (!links.length) return "";
    const linked = [...new Set(links.flatMap((l) => [l.a, l.b]))];
    const W = 600;
    const H = 92;
    const pos = {};
    linked.forEach((n, i) => (pos[n] = linked.length === 1 ? W / 2 : 70 + (i * (W - 140)) / (linked.length - 1)));
    const lines = links
      .map((l) => {
        const x1 = pos[l.a];
        const x2 = pos[l.b];
        const color = l.up ? speedColor(l.spd) : "#555";
        const dur = blinkDuration(l.bps);
        return `<line x1="${x1}" y1="46" x2="${x2}" y2="46" stroke="${color}" stroke-width="3" opacity=".35"/>
          <line x1="${x1}" y1="46" x2="${x2}" y2="46" stroke="${color}" stroke-width="3" stroke-dasharray="6 10" ${
            dur ? `style="animation: bp-flow ${(dur * 3).toFixed(2)}s linear infinite"` : ""
          }/>
          <text x="${(x1 + x2) / 2}" y="36" text-anchor="middle" fill="#bdbdbd" font-size="10">${esc(l.pa)} ⟷ ${esc(l.pb)} · ${esc(speedLabel(l.spd))}</text>
          <text x="${(x1 + x2) / 2}" y="64" text-anchor="middle" fill="${IN_COLOR}" font-size="10">${esc(fmtRate(l.bps))}</text>`;
      })
      .join("");
    const boxes = linked
      .map((n) => {
        const node = nodes[n];
        const health = node.attrs.health;
        const color = health ? GRADE_COLORS[health.grade] : "#69f0ae";
        return `<g transform="translate(${pos[n] - 62} 30)">
          <rect width="124" height="32" rx="10" fill="#151515" stroke="rgba(255,215,0,0.6)"/>
          <circle cx="14" cy="16" r="4" fill="${node.up ? color : "#ff5252"}" style="filter:drop-shadow(0 0 3px ${color})"/>
          <text x="26" y="20" fill="#ffd700" font-size="11" font-weight="600">${esc(String(node.name).slice(0, 16))}</text>
        </g>`;
      })
      .join("");
    return `<div class="topo"><svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W * 1.4}px;display:block;margin:0 auto">${lines}${boxes}</svg></div>`;
  }

  _renderSwitch(item) {
    const state = this._hass.states[item.entity];
    if (!state) {
      return `<div class="sw unavail">Entity ${esc(item.entity)} not found</div>`;
    }
    const a = state.attributes;
    let sys = a.system;
    if (!sys || !a.ports) {
      return `<div class="sw unavail">${esc(state.attributes.friendly_name || item.entity)}: waiting for data</div>`;
    }
    const offline = state.state === "unavailable";
    const names = item.port_names || {};
    const ports = a.ports.map(normPort).map((p) => (names[p.n] ? { ...p, a: String(names[p.n]) } : p));
    const eth = ports.filter((p) => p.k === "eth");
    const lags = ports.filter((p) => p.k === "lag");
    const lagColor = {};
    lags.forEach((lag, i) => (lagColor[lag.n] = LAG_COLORS[i % LAG_COLORS.length]));
    const title = item.name || sys.name || item.entity;
    sys = { ...sys, manufacturer: item.brand || sys.manufacturer, model: item.model || sys.model };
    const subParts = [sys.model, sys.firmware, sys.location, sys.host].filter(Boolean);
    const poe = a.poe;
    const totals = a.totals || {};
    const badSensors = (a.sensors || []).filter((s) => s.status === "bad" || s.status === "warning");

    const chips = [
      `<span class="chip">Up <b>${esc(fmtUptime(sys.uptime))}</b></span>`,
      sys.cpu != null ? `<span class="chip">CPU <b>${esc(sys.cpu)}%</b></span>` : "",
      `<span class="chip">Ports <b>${esc(totals.up)}/${esc(totals.total)}</b></span>`,
      `<span class="chip">&darr; <b>${esc(fmtRate(totals.in))}</b> &uarr; <b>${esc(fmtRate(totals.out))}</b></span>`,
      totals.day_in != null
        ? `<span class="chip">Today <b>&darr;${esc(fmtBytes(totals.day_in))} &uarr;${esc(fmtBytes(totals.day_out))}</b></span>`
        : "",
      poe ? `<span class="chip">PoE <b>${esc(poe.used)}/${esc(poe.budget)} W</b></span>` : "",
      a.health ? `<span class="chip ${a.health.grade === "critical" ? "bad" : ""}">Health <b style="color:${GRADE_COLORS[a.health.grade]}">${esc(a.health.score)}</b></span>` : "",
      ...badSensors.map((s) => `<span class="chip bad">${esc(s.name)}: ${esc(s.status)}</span>`),
    ].join("");

    const selected = this._selected[item.entity];
    const smallDevice = this._layout(item, eth).copper.length <= 8;
    const svg = this._narrow && !smallDevice
      ? this._renderStacked(item, sys, eth, lagColor, selected, a.sensors || [], poe)
      : this._renderPanel(item, sys, eth, lagColor, selected, a.sensors || [], poe, this._narrow ? 3 : 0);

    const legend = [
      ...lags.map(
        (lag) =>
          `<span class="lg"><i style="background:${lagColor[lag.n]}"></i>${esc(lag.n)} &middot; ${esc(
            speedLabel(lag.spd),
          )}${lag.mem && lag.mem.length ? ` &middot; ${esc(lag.mem.join("+"))}` : ""}</span>`,
      ),
      `<span class="lg"><i style="background:#00e5ff"></i>10G</span>`,
      `<span class="lg"><i style="background:#ffd700"></i>1G</span>`,
      `<span class="lg"><i style="background:#ff9f1a"></i>100M</span>`,
      `<span class="lg"><i style="background:#ff5252"></i>10M</span>`,
    ].join("");

    const hist = this._history[item.entity] || { in: [], out: [] };
    const traffic = `
      <div class="box">
        <h4>Traffic <span><span style="color:${IN_COLOR}">&darr; ${esc(fmtRate(totals.in))}</span> &nbsp; <span style="color:${OUT_COLOR}">&uarr; ${esc(fmtRate(totals.out))}</span></span></h4>
        ${this._renderSpark(hist)}
      </div>`;
    const poeBox = poe
      ? `
      <div class="box">
        <h4>PoE <span>${esc(poe.used)} W of ${esc(poe.budget)} W</span></h4>
        <div class="bar"><i style="width:${Math.min(100, poe.budget ? (poe.used / poe.budget) * 100 : 0).toFixed(1)}%"></i></div>
        <div class="muted">${esc(poe.ports)} powered device${poe.ports === 1 ? "" : "s"} &middot; ${poe.on ? "PSE on" : "PSE off"}</div>
        ${this._renderPoeList(item, eth)}
      </div>`
      : "";

    const detail =
      selected != null
        ? this._renderDetail(item, ports.find((p) => p.i === selected), lagColor)
        : this._renderNeighbors(item, eth);

    return `
      <div class="sw">
        <div class="hdr">
          <div class="ttl">
            <span class="state ${offline ? "off" : ""}"></span>
            ${this._narrow && smallDevice && item.logo ? `<img class="hlogo" src="${esc(item.logo)}" alt="">` : ""}
            <div style="min-width:0">
              <div class="name">${esc(title)}</div>
              <div class="sub">${esc(subParts.join(" · "))}</div>
            </div>
          </div>
          <div class="chips">${chips}</div>
        </div>
        <div class="panel">${svg}</div>
        <div class="legend">${legend}</div>
        <div class="row">${this._renderHealth(a.health, a.stp)}${traffic}${poeBox}</div>
        <div class="row">${detail}</div>
        ${offline ? `<div class="warn">Switch not reachable - showing last known state.</div>` : ""}
      </div>`;
  }

  _layout(item, eth) {
    let sfp = item.sfp_ports ?? this._config.sfp_ports;
    if (sfp == null) sfp = eth.length === 28 || eth.length === 52 ? 4 : 0;
    sfp = Math.max(0, Math.min(sfp, eth.length));
    const copper = eth.slice(0, eth.length - sfp);
    const fiber = eth.slice(eth.length - sfp);
    return { copper, fiber };
  }

  _renderStacked(item, sys, eth, lagColor, selected, sensors, poe) {
    // phone: one chassis, two port banks stacked (1-12 above 13-24 + SFP)
    const top = this._renderPanel(item, sys, eth, lagColor, selected, sensors, poe, 1, true);
    const bottom = this._renderPanel(item, sys, eth, lagColor, selected, sensors, poe, 2, true);
    const width = Math.max(top.width, bottom.width);
    const overlap = 14;
    const height = top.height + bottom.height - overlap;
    const screws = [height * 0.25, height * 0.75]
      .map(
        (y) =>
          `<circle cx="12" cy="${y}" r="3.2" fill="#000" stroke="#555"/><circle cx="${width - 12}" cy="${y}" r="3.2" fill="#000" stroke="#555"/>`,
      )
      .join("");
    // brand block in the free space above the SFP cage
    const x0 = width - 26 - 2 * 54 + 4;
    const ledColor = (match) => {
      const found = sensors.find((x) => x.name.toLowerCase().includes(match));
      if (!found) return null;
      return { good: "#69f0ae", warning: "#ffb300", bad: "#ff5252" }[found.status] || "#555";
    };
    const leds = [
      ["PWR", ledColor("power") || "#69f0ae"],
      ["FAN", ledColor("fan")],
      ["PoE", poe ? (poe.on ? "#ffb300" : "#555") : null],
    ].filter((led) => led[1]);
    const brandBlock = width - x0 > 80
      ? `${item.logo ? `<image href="${esc(item.logo)}" x="${x0}" y="18" width="100" height="38" preserveAspectRatio="xMinYMid meet"/>` : wordmark(sys.manufacturer, x0, 22, width - x0 - 22)}
        <text x="${x0}" y="${item.logo ? 70 : 62}" fill="#e0e0e0" font-size="11">${esc(sys.model || "")}</text>
        ${leds
          .map(
            ([label, color], i) =>
              `<circle cx="${x0 + 5 + i * 36}" cy="94" r="4" fill="${color}" style="filter:drop-shadow(0 0 3px ${color})"/><text x="${x0 + 12 + i * 36}" y="98" fill="#bdbdbd" font-size="9">${label}</text>`,
          )
          .join("")}`
      : "";
    return `<svg style="max-width:${Math.round(width * 2.6)}px;margin-top:8px" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" font-family="var(--primary-font-family, sans-serif)">
      ${top.defs}
      <rect x="1" y="1" width="${width - 2}" height="${height - 2}" rx="10" fill="url(#bp-chassis)" stroke="rgba(255,215,0,0.55)" stroke-width="1.5"/>
      <line x1="24" y1="${top.height - overlap / 2}" x2="${width - 24}" y2="${top.height - overlap / 2}" stroke="rgba(255,215,0,0.12)" stroke-dasharray="3 4"/>
      ${screws}
      <g>${top.inner}</g>
      ${brandBlock}
      <g transform="translate(0 ${top.height - overlap})">${bottom.inner}</g>
    </svg>`;
  }

  _renderPanel(item, sys, eth, lagColor, selected, sensors, poe, part, bare = false) {
    let { copper, fiber } = this._layout(item, eth);
    const compact = part > 0;
    const fiberAll = fiber.length;
    const single = copper.length <= 8;
    if (compact && part !== 3) {
      const totalCols = Math.ceil(copper.length / 2);
      const split = Math.min(totalCols, Math.max(1, Math.ceil(totalCols / 2 / 6) * 6)) * 2;
      if (part === 1) {
        copper = copper.slice(0, split);
        fiber = [];
      } else {
        copper = copper.slice(split);
      }
    }
    const PW = 46;
    const PH = 36;
    const PITCH = 54;
    const GROUP = 6;
    const GROUP_GAP = 12;
    const LEFT = compact ? 24 : 156;
    let TOP = 34;
    const ROW2 = TOP + PH + 24;
    const wanGap = single && copper.some((p) => /^wan/i.test(p.n)) ? 16 : 0;
    const cols = single ? copper.length : Math.ceil(copper.length / 2);
    const groups = Math.max(1, Math.ceil(cols / GROUP));
    const copperWidth = cols * PITCH + (groups - 1) * GROUP_GAP + wanGap;
    const fiberCols = Math.ceil(fiber.length / 2);
    const fiberX = LEFT + copperWidth + (fiber.length ? 22 : 0);
    let width = fiberX + fiberCols * PITCH + 26;
    if (part === 1 && fiberAll) width += 22 + Math.ceil(fiberAll / 2) * PITCH;
    let height = ROW2 + PH + 30;
    if (single) {
      height = compact ? TOP + PH + 26 : item.logo ? 140 : 132;
      TOP = Math.round((height - PH) / 2) + 2;
    }

    const parts = [];
    const logo = item.logo;
    const ledTop = logo ? 90 : 72;
    const brand = compact
      ? ""
      : logo
      ? `<image href="${esc(logo)}" x="26" y="12" width="112" height="44" preserveAspectRatio="xMinYMid meet"/>
      <text x="26" y="72" fill="#e0e0e0" font-size="12">${esc(sys.model || "")}</text>`
      : `${wordmark(sys.manufacturer, 26, 14, 130)}
      <text x="26" y="57" fill="#e0e0e0" font-size="12">${esc(sys.model || "")}</text>
      <text x="26" y="${height - 16}" fill="rgba(255,215,0,0.45)" font-size="9" letter-spacing="2">BACKPLANE</text>`;
    const defs = `
      <defs>
        <linearGradient id="bp-chassis" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#262626"/><stop offset="1" stop-color="#0c0c0c"/>
        </linearGradient>
        <linearGradient id="bp-jack" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#050505"/><stop offset="1" stop-color="#1a1a1a"/>
        </linearGradient>
      </defs>`;
    if (!bare) parts.push(`${defs}
      <rect x="1" y="1" width="${width - 2}" height="${height - 2}" rx="10" fill="url(#bp-chassis)" stroke="rgba(255,215,0,0.55)" stroke-width="1.5"/>
      <circle cx="12" cy="${height / 2 - 18}" r="3.2" fill="#000" stroke="#555"/>
      <circle cx="12" cy="${height / 2 + 18}" r="3.2" fill="#000" stroke="#555"/>
      <circle cx="${width - 12}" cy="${height / 2 - 18}" r="3.2" fill="#000" stroke="#555"/>
      <circle cx="${width - 12}" cy="${height / 2 + 18}" r="3.2" fill="#000" stroke="#555"/>
      ${brand}`);

    // status LEDs (PWR / FAN / PoE)
    const sensorColor = (match) => {
      const s = sensors.find((x) => x.name.toLowerCase().includes(match));
      if (!s) return null;
      if (s.status === "good") return "#69f0ae";
      if (s.status === "warning") return "#ffb300";
      if (s.status === "bad") return "#ff5252";
      return "#555";
    };
    const leds = [
      ["PWR", sensorColor("power") || "#69f0ae"],
      ["FAN", sensorColor("fan")],
      ["PoE", poe ? (poe.on ? "#ffb300" : "#555") : null],
    ].filter((led) => led[1] && !compact);
    leds.forEach(([label, color], i) => {
      const y = ledTop + i * 16;
      parts.push(
        `<circle cx="31" cy="${y}" r="4" fill="${color}" style="filter:drop-shadow(0 0 3px ${color})"/>` +
          `<text x="41" y="${y + 4}" fill="#bdbdbd" font-size="10">${label}</text>`,
      );
    });

    const place = (port, x, y, bottom, isFiber) => {
      const up = port.up;
      const color = up ? speedColor(port.spd) : port.adm ? "#3a3a3a" : "#7a2a2a";
      const util = up && port.spd ? Math.max(port.in, port.out) / (port.spd * 1e6) : 0;
      const utilWidth = up ? Math.max(util > 0 ? 2 : 0, Math.min(1, Math.sqrt(util)) * (PW - 8)) : 0;
      const blink = up ? blinkDuration(Math.max(port.in, port.out)) : null;
      const poeOn = port.poe === "delivering";
      const isSel = selected === port.i;
      const lag = port.lag ? lagColor[port.lag] : null;
      const tip = [
        `Port ${port.n}${port.a ? ` (${port.a})` : ""}`,
        up ? speedLabel(port.spd) : port.adm ? "no link" : "disabled",
        up ? `in ${fmtRate(port.in)} / out ${fmtRate(port.out)}` : "",
        port.pw ? `PoE ${port.pw} W` : poeOn ? "PoE on" : "",
        port.lag ? `trunk ${port.lag}` : "",
        port.nb ? `LLDP: ${port.nb.name || ""} ${port.nb.port ? `(${port.nb.port})` : ""}` : "",
      ]
        .filter(Boolean)
        .join("\n");

      const flip = bottom ? `transform="translate(0 ${PH}) scale(1 -1)"` : "";
      const socket = isFiber
        ? `<rect x="7" y="8" width="${PW - 14}" height="${PH - 16}" rx="2" fill="url(#bp-jack)" stroke="#333"/>
           <rect x="12" y="13" width="${PW - 24}" height="${PH - 26}" rx="1" fill="#000"/>`
        : `<path d="M8 7 H${PW - 8} V${PH - 13} H${PW - 15} V${PH - 8} H15 V${PH - 13} H8 Z" fill="url(#bp-jack)" stroke="#2c2c2c"/>
           <path d="M13 9 h${PW - 26}" stroke="#7a6a20" stroke-width="2" stroke-dasharray="2 2" opacity="${up ? 0.9 : 0.35}"/>`;
      const linkLed = `<rect x="4" y="2.5" width="9" height="3.2" rx="1" fill="${up ? color : "#262626"}" ${
        up ? `style="filter:drop-shadow(0 0 3px ${color})"` : ""
      }/>`;
      const actLed = `<rect class="act ${blink ? "on" : ""}" x="${PW - 13}" y="2.5" width="9" height="3.2" rx="1" fill="${
        up ? "#76ff03" : "#262626"
      }" ${blink ? `style="--d:${blink}s"` : ""}/>`;
      const utilBar = utilWidth
        ? `<rect x="4" y="${PH - 5}" width="${utilWidth.toFixed(1)}" height="2.6" rx="1" fill="${color}" opacity=".9"/>`
        : "";
      const bolt = poeOn
        ? `<path class="poebolt" d="M${PW / 2 + 1} 12 l-5 8 h4 l-2 7 l6 -9 h-4 z" fill="#ffb300"/>`
        : "";
      const ring = lag
        ? `<rect x="-3.5" y="-3.5" width="${PW + 7}" height="${PH + 7}" rx="6" fill="none" stroke="${lag}" stroke-width="1.6" stroke-dasharray="4 3"/>`
        : "";
      const nbDot = port.nb ? `<circle cx="${PW - 4}" cy="${PH - 9}" r="2.6" fill="#40c4ff" style="filter:drop-shadow(0 0 3px #40c4ff)"/>` : "";
      const disabledX = !port.adm
        ? `<path d="M14 10 L${PW - 14} ${PH - 10} M${PW - 14} 10 L14 ${PH - 10}" stroke="#ff5252" stroke-width="2"/>`
        : "";
      const isWan = /^wan/i.test(port.n);
      const labelY = bottom ? PH + 13 : -6;
      return `
        <g class="port ${isSel ? "sel" : ""}" data-port="${port.i}" data-entity="${esc(item.entity)}" transform="translate(${x} ${y})">
          <title>${esc(tip)}</title>
          ${ring}
          <rect class="body" x="0" y="0" width="${PW}" height="${PH}" rx="4" fill="#141414" stroke="${up ? color : "#444"}" stroke-width="1.4" ${
            up ? `style="filter:drop-shadow(0 0 2px ${color}66)"` : ""
          }/>
          <g ${flip}>${socket}${linkLed}${actLed}${utilBar}</g>
          ${bolt}${nbDot}${disabledX}
          <text x="${PW / 2}" y="${labelY}" text-anchor="middle" fill="${isWan ? "#40c4ff" : up ? "#e0e0e0" : "#777"}" font-size="10" ${isWan ? 'font-weight="700"' : ""}>${esc(isWan ? port.n.toUpperCase() : port.n)}</text>
        </g>`;
    };

    let pastWan = 0;
    copper.forEach((port, k) => {
      const col = single ? k : Math.floor(k / 2);
      const bottom = single ? false : k % 2 === 1;
      const x = LEFT + col * PITCH + Math.floor(col / GROUP) * GROUP_GAP + pastWan;
      parts.push(place(port, x, bottom ? ROW2 : TOP, bottom, false));
      if (single && /^wan/i.test(port.n)) pastWan = wanGap;
    });
    fiber.forEach((port, k) => {
      const col = Math.floor(k / 2);
      const bottom = k % 2 === 1;
      parts.push(place(port, fiberX + col * PITCH, bottom ? ROW2 : TOP, bottom, true));
    });
    if (fiber.length) {
      parts.push(
        `<text x="${fiberX + (fiberCols * PITCH - 8) / 2}" y="${height - 6}" text-anchor="middle" fill="#777" font-size="9" letter-spacing="1">SFP</text>`,
      );
    }
    if (bare) return { defs, inner: parts.join(""), width, height };
    const maxWidth = Math.round(width * (compact ? 2.6 : 1.25));
    return `<svg style="max-width:${maxWidth}px;${compact ? "margin-top:8px" : ""}" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" font-family="var(--primary-font-family, sans-serif)">${parts.join("")}</svg>`;
  }

  _renderSpark(hist) {
    const W = 300;
    const H = 64;
    const now = Date.now();
    const start = now - 3600 * 1000;
    const all = hist.in.concat(hist.out);
    if (hist.in.length < 2) {
      return `<div class="spark" style="display:flex;align-items:center;justify-content:center;font-size:11px;opacity:.6">collecting samples...</div>`;
    }
    const max = Math.max(1000, ...all.map((p) => p[1])) * 1.1;
    const sx = (t) => ((t - start) / (now - start)) * W;
    const sy = (v) => H - 4 - (v / max) * (H - 10);
    const line = (points) => points.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)} ${sy(p[1]).toFixed(1)}`).join(" ");
    const inLine = line(hist.in);
    const first = hist.in[0];
    const last = hist.in[hist.in.length - 1];
    const area = `${inLine} L${sx(last[0]).toFixed(1)} ${H} L${sx(first[0]).toFixed(1)} ${H} Z`;
    return `<div class="sparkwrap"><span class="sl tl">${esc(fmtRate(max / 1.1))}</span><span class="sl br">60 min</span>
      <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <defs><linearGradient id="bp-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="${IN_COLOR}" stop-opacity=".35"/><stop offset="1" stop-color="${IN_COLOR}" stop-opacity="0"/>
        </linearGradient></defs>
        <line x1="0" y1="${H - 4}" x2="${W}" y2="${H - 4}" stroke="rgba(255,255,255,.08)"/>
        <path d="${area}" fill="url(#bp-area)"/>
        <path d="${inLine}" fill="none" stroke="${IN_COLOR}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
        <path d="${line(hist.out)}" fill="none" stroke="${OUT_COLOR}" stroke-width="1.4" vector-effect="non-scaling-stroke" opacity=".9"/>
      </svg></div>`;
  }

  _renderHealth(health, stp) {
    if (!health) return "";
    const color = GRADE_COLORS[health.grade] || "#888";
    const r = 26;
    const circ = 2 * Math.PI * r;
    const dash = ((health.score / 100) * circ).toFixed(1);
    const ring = `<svg viewBox="0 0 64 64" width="64" height="64">
      <circle cx="32" cy="32" r="${r}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="6"/>
      <circle cx="32" cy="32" r="${r}" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round"
        stroke-dasharray="${dash} ${circ.toFixed(1)}" transform="rotate(-90 32 32)" style="filter:drop-shadow(0 0 4px ${color})"/>
      <text x="32" y="37" text-anchor="middle" fill="${color}" font-size="16" font-weight="700">${esc(health.score)}</text>
    </svg>`;
    const shown = health.findings.slice(0, 5);
    const more = health.findings.length - shown.length;
    const list = shown.length
      ? shown
          .map((f) => `<div class="fd"><i style="background:${LEVEL_COLORS[f.level]};box-shadow:0 0 5px ${LEVEL_COLORS[f.level]}"></i><span>${esc(f.msg)}</span></div>`)
          .join("") + (more > 0 ? `<div class="muted">+${more} more</div>` : "")
      : `<div class="fd"><i style="background:#69f0ae;box-shadow:0 0 5px #69f0ae"></i><span>All ports and hardware healthy</span></div>`;
    const stpLine =
      stp && stp.tc != null
        ? `<div class="muted" style="margin-top:6px">Spanning tree: ${esc(stp.tc)} topology changes${stp.since != null ? ` &middot; last ${esc(fmtAgo(stp.since))} ago` : ""}</div>`
        : "";
    return `<div class="box"><h4>Health <span style="color:${color}">${esc(health.grade)}</span></h4><div class="hb">${ring}<div>${list}${stpLine}</div></div></div>`;
  }

  _renderPoeList(item, eth) {
    const powered = eth.filter((p) => p.poe === "delivering");
    if (!powered.length) return "";
    return `<div class="list" style="margin-top:6px">${powered
      .map(
        (p) => `<div class="li" data-port="${p.i}" data-entity="${esc(item.entity)}">
          <span class="p">${esc(p.n)}</span>
          <span class="n">${esc((p.nb && p.nb.name) || p.a || "powered device")}</span>
          <span class="r">${p.pw != null ? `${esc(p.pw)} W` : "on"}</span></div>`,
      )
      .join("")}</div>`;
  }

  _renderNeighbors(item, eth) {
    const withNb = [...eth, ...lagPorts(item, this._hass)].filter((p) => p.nb || (p.mac && p.mac.length && p.mac.length <= 3 && p.mac.some(macName)));
    const busiest = eth
      .filter((p) => p.up)
      .sort((a, b) => Math.max(b.in, b.out) - Math.max(a.in, a.out))
      .slice(0, 5);
    const nbList = withNb.length
      ? withNb
          .map(
            (p) => `<div class="li" data-port="${p.i}" data-entity="${esc(item.entity)}">
              <span class="p">${esc(p.n)}</span>
              <span class="n">${esc(p.nb ? p.nb.name || p.nb.descr || "unknown" : [...new Set(p.mac.map(macName).filter(Boolean))].join(", "))}</span>
              <span class="r">${esc(p.nb ? p.nb.port || "LLDP" : (p.mac.find((m) => m.ip) || {}).ip || "MAC")}</span></div>`,
          )
          .join("")
      : `<div class="muted">No neighbours or known devices found.</div>`;
    const topList = busiest.length
      ? busiest
          .map(
            (p) => `<div class="li" data-port="${p.i}" data-entity="${esc(item.entity)}">
              <span class="p">${esc(p.n)}</span>
              <span class="n">${esc(portLabel(p) || speedLabel(p.spd))}</span>
              <span class="r">&darr;${esc(fmtRate(p.in))} &uarr;${esc(fmtRate(p.out))}</span></div>`,
          )
          .join("")
      : `<div class="muted">No active ports.</div>`;
    return `
      <div class="box"><h4>Neighbours &amp; devices <span>LLDP + MAC</span></h4><div class="list">${nbList}</div></div>
      <div class="box"><h4>Top talkers <span>tap a port for details</span></h4><div class="list">${topList}</div></div>`;
  }

  _renderDetail(item, port, lagColor) {
    if (!port) return "";
    const kv = (k, v, color) =>
      `<div class="kv"><div class="k">${esc(k)}</div><div class="v" ${color ? `style="color:${color}"` : ""}>${esc(v)}</div></div>`;
    const util =
      port.up && port.spd ? `${((Math.max(port.in, port.out) / (port.spd * 1e6)) * 100).toFixed(2)} %` : "-";
    const fields = [
      kv("Status", port.up ? "link up" : port.adm ? "no link" : "disabled", port.up ? "#69f0ae" : "#ff8a80"),
      kv("Speed", port.up ? speedLabel(port.spd) : "-", port.up ? speedColor(port.spd) : null),
      kv("In", fmtRate(port.in), IN_COLOR),
      kv("Out", fmtRate(port.out), OUT_COLOR),
      port.vd ? kv("Today", `\u2193 ${fmtBytes(port.vd[0])}  \u2191 ${fmtBytes(port.vd[1])}`) : "",
      kv("Utilization", util),
      kv("Errors in/out", `${port.ie} / ${port.oe}`, port.ie || port.oe ? "#ffb300" : null),
      port.err_h != null ? kv("Errors last hour", port.err_h, port.err_h ? "#ffb300" : null) : "",
      port.fcs != null ? kv("CRC errors", port.fcs, port.fcs ? "#ffb300" : null) : "",
      port.dup ? kv("Duplex", port.dup, port.dup === "half" ? "#ffb300" : null) : "",
      port.ls ? kv(port.up ? "Link up since" : "Down since", fmtSince(port.ls)) : "",
      port.flaps_h ? kv("Link changes (1 h)", port.flaps_h, "#ffb300") : "",
      port.bc != null ? kv("Broadcast", `${port.bc} pkt/s`, port.bc >= 1000 ? "#ff5252" : null) : "",
      port.vlan != null ? kv("VLAN (PVID)", port.vlan) : "",
      port.poe ? kv("PoE", port.pw != null ? `${port.pw} W` : port.poe, port.poe === "delivering" ? "#ffb300" : null) : "",
      port.lag ? kv("Trunk", port.lag, lagColor[port.lag]) : "",
      port.nb ? kv("Neighbour", port.nb.name || "-", "#40c4ff") : "",
      port.nb && port.nb.port ? kv("Remote port", port.nb.port) : "",
    ].join("");
    return `
      <div class="box" style="flex-basis:100%">
        <h4>Port ${esc(port.n)}${port.a ? ` &middot; ${esc(port.a)}` : ""}
          <span class="close" data-close="1" data-entity="${esc(item.entity)}">close &times;</span></h4>
        <div class="grid">${fields}</div>
        ${port.nb && port.nb.descr ? `<div class="muted">${esc(port.nb.descr)}</div>` : ""}
        ${this._renderDevices(port)}
        <div style="margin-top:8px">${this._renderSpark(((this._portHistory[item.entity] || {})[port.i]) || { in: [], out: [] })}</div>
      </div>`;
  }

  _renderDevices(port) {
    if (port.mac && port.mac.length) {
      return `<div class="devs"><div class="k" style="font-size:10px;opacity:.6;text-transform:uppercase;letter-spacing:.5px">Devices on this port</div>${port.mac
        .map(
          (m) => `<div class="li" style="cursor:default"><span class="p" style="min-width:0">●</span><span class="n">${esc(m.n || (m.v ? `${m.v} · ${m.m}` : m.m))}</span><span class="r">${esc(m.ip || (m.n ? m.m : ""))}</span></div>`,
        )
        .join("")}</div>`;
    }
    if (port.mac_n) return `<div class="muted">${esc(port.mac_n)} MAC addresses behind this port (uplink)</div>`;
    return "";
  }
}

class BackplaneCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  _render() {
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) =>
        ({ entities: "Backplane devices", sfp_ports: "SFP ports at the end (empty = auto)", topology: "Show topology links" })[schema.name] || schema.name;
      this._form.addEventListener("value-changed", (ev) => this._changed(ev.detail.value));
      this.appendChild(this._form);
    }
    const list = this._config.entities || (this._config.entity ? [this._config.entity] : []);
    this._form.schema = [
      { name: "entities", selector: { entity: { multiple: true, filter: { integration: "backplane", domain: "sensor" } } } },
      { name: "sfp_ports", selector: { number: { min: 0, max: 8, mode: "box" } } },
      { name: "topology", selector: { boolean: {} } },
    ];
    this._form.data = {
      entities: list.map((e) => (typeof e === "string" ? e : e.entity)),
      sfp_ports: this._config.sfp_ports,
      topology: this._config.topology !== false,
    };
    if (this._hass) this._form.hass = this._hass;
  }

  _changed(value) {
    const previous = this._config.entities || (this._config.entity ? [this._config.entity] : []);
    const byId = {};
    for (const e of previous) byId[typeof e === "string" ? e : e.entity] = e;
    const config = { ...this._config, entities: (value.entities || []).map((id) => byId[id] || id) };
    delete config.entity;
    if (value.sfp_ports === undefined || value.sfp_ports === null || value.sfp_ports === "") delete config.sfp_ports;
    else config.sfp_ports = Number(value.sfp_ports);
    if (value.topology === false) config.topology = false;
    else delete config.topology;
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }
}

if (!customElements.get("backplane-card-editor")) customElements.define("backplane-card-editor", BackplaneCardEditor);

if (!customElements.get("backplane-card")) {
  customElements.define("backplane-card", BackplaneCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "backplane-card",
    name: "Backplane",
    description: "Live switch front panel: link speed, traffic, PoE, trunks and LLDP neighbours.",
    preview: true,
    documentationURL: "https://github.com/mb26-dev/ha-backplane",
  });
  console.info(`%c BACKPLANE %c v${BP_VERSION} `, "background:#ffd700;color:#000;font-weight:700", "background:#222;color:#ffd700");
}
