"use strict";
/* SignalWalk dashboard. Plain JavaScript and <canvas>; no build step, no external requests.
   All server text is inserted with textContent, never innerHTML. */

const PALETTE = [[-95, [18, 10, 42]], [-85, [58, 15, 96]], [-75, [140, 40, 120]], [-67, [220, 80, 90]],
                 [-60, [245, 140, 60]], [-52, [250, 200, 80]], [-42, [252, 245, 170]]];
const INK = "#14212e";
const WALL_PX = { light: 1.6, interior: 3, heavy: 5 };

const state = { cfg: null, plan: null, points: [], analysis: null, busy: false,
                showConfidence: false, showAdvice: true, hover: null };
const $ = (id) => document.getElementById(id);

function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}

function rssiRgb(dbm) {
  if (dbm <= PALETTE[0][0]) return PALETTE[0][1];
  for (let i = 1; i < PALETTE.length; i++) {
    const [d1, c1] = PALETTE[i], [d0, c0] = PALETTE[i - 1];
    if (dbm <= d1) { const t = (dbm - d0) / (d1 - d0); return c0.map((a, k) => Math.round(a + (c1[k] - a) * t)); }
  }
  return PALETTE[PALETTE.length - 1][1];
}
const rgbCss = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
const fmtDbm = (v) => `${v.toFixed(0)} dBm`;

async function api(url, opts) {
  const res = await fetch(url, opts);
  let body = null;
  try { body = await res.json(); } catch (_) { /* not JSON */ }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${res.status}`);
  }
  return body;
}
const post = (url, data) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data || {}) });

function toast(msg) {
  const el = $("toast");
  el.textContent = msg; el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { el.hidden = true; }, 4000);
}

/* ------------------------------------------------------------ map drawing */

function canvasSize() {
  const c = $("map"), dpr = window.devicePixelRatio || 1;
  const w = Math.max(320, $("mapwrap").clientWidth);
  const hgt = Math.round(w * state.plan.height_m / state.plan.width_m);
  c.style.height = hgt + "px";
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(hgt * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(hgt * dpr); }
  const ctx = c.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h: hgt, k: w / state.plan.width_m };
}

function haloText(ctx, text, x, y, size, weight = 600) {
  ctx.font = `${weight} ${size}px "Avenir Next","Segoe UI",system-ui,sans-serif`;
  ctx.textAlign = "center"; ctx.lineJoin = "round"; ctx.lineWidth = 3.2;
  ctx.strokeStyle = "#0b1320"; ctx.strokeText(text, x, y);
  ctx.fillStyle = "#fff"; ctx.fillText(text, x, y);
}

function heatLayer(grid, colorAt) {
  const off = document.createElement("canvas");
  off.width = grid.nx; off.height = grid.ny;
  const octx = off.getContext("2d");
  const img = octx.createImageData(grid.nx, grid.ny);
  for (let j = 0; j < grid.ny; j++) for (let i = 0; i < grid.nx; i++) {
    const p = (j * grid.nx + i) * 4, c = colorAt(j, i);
    img.data[p] = c[0]; img.data[p + 1] = c[1]; img.data[p + 2] = c[2]; img.data[p + 3] = c[3];
  }
  octx.putImageData(img, 0, 0);
  return off;
}

function drawMap() {
  if (!state.plan) return;
  const { ctx, w, h: hgt, k } = canvasSize();
  const plan = state.plan, a = state.analysis;
  ctx.clearRect(0, 0, w, hgt);
  ctx.fillStyle = "#f4f6f8"; ctx.fillRect(0, 0, w, hgt);

  if (a) {
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
    const g = a.grid;
    ctx.drawImage(heatLayer(g, (j, i) => [...rssiRgb(g.mean[j][i]), 255]), 0, 0, w, hgt);
    if (state.showConfidence) {
      ctx.drawImage(heatLayer(g, (j, i) => [255, 255, 255, Math.round(Math.max(0, Math.min(0.62, (g.std[j][i] - 2.0) / 3.5)) * 255)]), 0, 0, w, hgt);
    }
  }
  for (const wall of plan.walls) {                       // white halo, then ink
    ctx.lineCap = "round";
    ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = WALL_PX[wall.kind] + 2.5;
    ctx.beginPath(); ctx.moveTo(wall.x1 * k, wall.y1 * k); ctx.lineTo(wall.x2 * k, wall.y2 * k); ctx.stroke();
    ctx.strokeStyle = INK; ctx.lineWidth = WALL_PX[wall.kind];
    ctx.beginPath(); ctx.moveTo(wall.x1 * k, wall.y1 * k); ctx.lineTo(wall.x2 * k, wall.y2 * k); ctx.stroke();
  }
  for (const r of plan.rooms) haloText(ctx, r.name, (r.x + r.w / 2) * k, (r.y + 0.34) * k, 11);
  if (a) for (const z of a.zones.slice(0, 6)) haloText(ctx, `${z.severity} #${z.id}`, z.x * k, z.y * k + 4, 12, 800);

  state.points.forEach((p) => {
    ctx.beginPath(); ctx.arc(p.x * k, p.y * k, 5, 0, Math.PI * 2);
    ctx.fillStyle = "#fff"; ctx.fill(); ctx.strokeStyle = INK; ctx.lineWidth = 1.6; ctx.stroke();
    haloText(ctx, p.rssi_dbm.toFixed(0), p.x * k, p.y * k - 9, 10, 700);
  });

  if (a && a.suggestions && state.showAdvice) {
    const s = a.suggestions;
    s.next_spots.forEach((p) => {
      ctx.beginPath(); ctx.arc(p.x * k, p.y * k, 12, 0, Math.PI * 2);
      ctx.setLineDash([4, 3]); ctx.strokeStyle = "#fff"; ctx.lineWidth = 3; ctx.stroke();
      ctx.strokeStyle = INK; ctx.lineWidth = 1.5; ctx.stroke(); ctx.setLineDash([]);
      haloText(ctx, "?", p.x * k, p.y * k + 4, 12, 800);
    });
    const ex = s.extender.suggestion;
    if (ex) {
      ctx.save(); ctx.translate(ex.x * k, ex.y * k); ctx.rotate(Math.PI / 4);
      ctx.fillStyle = "#9ec5ff"; ctx.strokeStyle = INK; ctx.lineWidth = 2; ctx.fillRect(-8, -8, 16, 16); ctx.strokeRect(-8, -8, 16, 16);
      ctx.restore(); haloText(ctx, "E", ex.x * k, ex.y * k + 4, 11, 800);
    }
    s.router.suggestions.forEach((p, i) => {
      ctx.beginPath(); ctx.arc(p.x * k, p.y * k, 12, 0, Math.PI * 2);
      ctx.fillStyle = "#22d3a6"; ctx.fill(); ctx.strokeStyle = INK; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = INK; ctx.font = "800 13px system-ui,sans-serif"; ctx.textAlign = "center"; ctx.fillText(String(i + 1), p.x * k, p.y * k + 4.5);
    });
  }
  const [rx, ry] = [plan.router.x * k, plan.router.y * k];
  ctx.fillStyle = INK; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.roundRect ? ctx.roundRect(rx - 10, ry - 10, 20, 20, 4) : ctx.rect(rx - 10, ry - 10, 20, 20); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#fff"; ctx.font = "800 12px system-ui,sans-serif"; ctx.textAlign = "center"; ctx.fillText("R", rx, ry + 4.5);
}

function drawLegend() {
  const c = $("legend-bar"), ctx = c.getContext("2d");
  for (let x = 0; x < c.width; x++) { ctx.fillStyle = rgbCss(rssiRgb(-90 + (x / c.width) * 48)); ctx.fillRect(x, 0, 1, c.height); }
}

/* ------------------------------------------------------------------ panels */

function renderSummary(a) {
  const box = $("summary"); box.replaceChildren();
  const c = a.coverage, t = a.thresholds;
  const segs = [["#fcf1aa", c.strong_pct, `strong (>= ${t.strong_dbm})`], ["#f08c3c", Math.max(0, c.ok_pct - c.strong_pct), "OK"],
                ["#b5387a", c.weak_pct, `weak (${t.dead_dbm} to ${t.weak_dbm})`], ["#2b0f4f", c.dead_pct, `dead (< ${t.dead_dbm})`]];
  const bar = h("div", { class: "stack", role: "img", "aria-label": `${c.ok_pct}% of the floor has OK signal` });
  for (const [col, val] of segs) { const seg = h("i"); seg.style.width = val + "%"; seg.style.background = col; bar.append(seg); }
  box.append(h("div", { class: "big" }, `${c.ok_pct.toFixed(0)}%`, h("small", { text: `  of the floor has OK signal (>= ${t.weak_dbm} dBm)` })), bar,
             h("div", { class: "keys" }, segs.map(([col, val, label]) => { const b = h("b"); b.style.background = col; return h("span", {}, b, `${val.toFixed(0)}% ${label}`); })));
  if (a.cv) {
    box.append(h("p", { class: "muted", text: `Typical map error about ${a.cv.rmse_hybrid} dB (leave-one-out over ${a.cv.n} spots). Plain interpolation would be off by ${a.cv.rmse_idw} dB.` }));
  } else box.append(h("p", { class: "muted", text: a.n_points ? "Need 5 or more measurements to estimate the map error." : "Click on the plan to take a first measurement." }));
}

function renderAdvice(a) {
  const box = $("advice"); box.replaceChildren();
  const s = a.suggestions;
  if (!s) { box.append(h("p", { class: "muted", text: "Take at least 3 measurements to get advice." })); return; }
  const r = s.router;
  const routerBlock = h("div", { class: "adv" }, h("h3", { text: `Move the router (now about ${r.baseline_pct}% OK)` }));
  if (!r.suggestions.length) routerBlock.append(h("p", { class: "muted", text: "No allowed position found." }));
  r.suggestions.forEach((p, i) => routerBlock.append(h("div", { class: "adv-item" }, h("span", { class: "dot", text: String(i + 1) }),
    h("span", {}, `${p.room} (${p.x}, ${p.y}): about ${p.expected_coverage_pct}% `, h("span", { class: "gain", text: `${p.gain_pp >= 0 ? "+" : ""}${p.gain_pp} points` })))));
  box.append(routerBlock);
  const e = s.extender.suggestion;
  box.append(h("div", { class: "adv" }, h("h3", { text: "Or add an extender" }),
    e ? h("div", { class: "adv-item" }, h("span", { class: "dot ext", text: "E" }),
        h("span", {}, `${e.room} (${e.x}, ${e.y}): about ${e.expected_coverage_pct}% `, h("span", { class: "gain", text: `+${e.gain_pp} points` }), ` . It would hear the router at ${e.hears_router_dbm} dBm.`))
      : h("p", { class: "muted", text: `No spot hears the router well enough (>= ${s.extender.backhaul_min_dbm} dBm).` })));
  box.append(h("div", { class: "adv" }, h("h3", { text: "Measure next (most uncertain)" }),
    s.next_spots.length ? s.next_spots.map((p) => h("div", { class: "adv-item" }, h("span", { class: "dot q", text: "?" }), h("span", { text: `${p.room} (${p.x}, ${p.y}): the map cannot tell weak from OK here.` })))
                        : h("p", { class: "muted", text: "The map is fairly sure everywhere." })));
  box.append(h("p", { class: "muted", text: `Advice is a model estimate (error about ${r.model_rmse_db} dB). Signal strength only, not speed.` }));
}

function renderZones(a) {
  const box = $("zones"); box.replaceChildren();
  if (!a.n_points) { box.append(h("p", { class: "muted", text: "Nothing measured yet." })); return; }
  if (!a.zones.length) { box.append(h("p", { class: "muted", text: "No weak or dead zones found." })); return; }
  for (const z of a.zones) box.append(h("div", { class: "zone" }, h("span", { class: "tag " + z.severity, text: z.severity }),
    `${z.area_m2} m², worst ${fmtDbm(z.min_dbm)}. `, h("span", { class: "muted", text: z.rooms.map((r) => `${r.name} ${Math.round(r.share * 100)}%`).join(", ") })));
}

function renderRooms(a) {
  const box = $("rooms"); box.replaceChildren();
  for (const r of a.rooms) {
    const bar = h("div", { class: "bar" }, (() => { const i = h("i"); i.style.width = r.ok_pct + "%"; return i; })());
    box.append(h("div", { class: "room", title: `${r.measured_points} measured spot(s); worst ${fmtDbm(r.worst_dbm)}` },
      h("span", {}, h("span", { class: "tag " + r.grade, text: r.grade }), r.room), bar, h("span", { class: "val", text: fmtDbm(r.median_dbm) })));
  }
}

function renderWarnings(a) {
  const ul = $("warnings"); ul.replaceChildren();
  for (const w of a.warnings) ul.append(h("li", { text: w }));
  $("card-warnings").hidden = a.warnings.length === 0;
}

function renderPoints() {
  const ul = $("points"); ul.replaceChildren();
  $("point-count").textContent = `(${state.points.length})`;
  state.points.forEach((p, i) => ul.append(h("li", {}, h("span", { class: "n", text: String(i + 1) }),
    h("span", { text: `(${p.x.toFixed(1)}, ${p.y.toFixed(1)}) m: ${p.rssi_dbm.toFixed(0)} dBm` + (p.spread_db >= 6 ? "  (noisy)" : "") }),
    h("button", { class: "btn small", type: "button", "aria-label": `Delete measurement ${i + 1}`, onclick: () => removePoint(i), text: "Delete" }))));
}

async function refresh() {
  const st = await api("/api/state");
  state.points = st.measurements;
  state.analysis = await api("/api/analysis");
  const a = state.analysis;
  renderSummary(a); renderAdvice(a); renderZones(a); renderRooms(a); renderWarnings(a); renderPoints();
  $("btn-undo").disabled = state.points.length === 0;
  drawMap();
}

/* ----------------------------------------------------------------- actions */

async function measureAt(x, y) {
  if (state.busy) return;
  state.busy = true; $("busy").hidden = state.cfg.mode !== "real";
  try {
    const r = await post("/api/measure", { x, y });
    toast(`${fmtDbm(r.measurement.rssi_dbm)} at (${x.toFixed(1)}, ${y.toFixed(1)}) m`);
    await refresh();
  } catch (err) { toast(err.message); }
  finally { state.busy = false; $("busy").hidden = true; }
}

async function removePoint(i) {
  try { await api(`/api/measurements/${i}`, { method: "DELETE" }); await refresh(); } catch (err) { toast(err.message); }
}

function pointerToMeters(ev) {
  const rect = $("map").getBoundingClientRect();
  return [(ev.clientX - rect.left) / rect.width * state.plan.width_m, (ev.clientY - rect.top) / rect.height * state.plan.height_m];
}

function onHover(ev) {
  const tip = $("tooltip"), a = state.analysis;
  if (!a) return;
  const [x, y] = pointerToMeters(ev), g = a.grid;
  const i = Math.min(g.nx - 1, Math.max(0, Math.floor(x / state.plan.width_m * g.nx)));
  const j = Math.min(g.ny - 1, Math.max(0, Math.floor(y / state.plan.height_m * g.ny)));
  const rect = $("mapwrap").getBoundingClientRect();
  tip.hidden = false;
  tip.textContent = `(${x.toFixed(1)}, ${y.toFixed(1)}) m: ${fmtDbm(g.mean[j][i])} ± ${g.std[j][i].toFixed(0)} dB`;
  tip.style.left = (ev.clientX - rect.left) + "px"; tip.style.top = (ev.clientY - rect.top) + "px";
}

async function init() {
  try {
    const st = await api("/api/state");
    state.cfg = st; state.plan = st.floorplan;
  } catch (err) { $("hint").textContent = `Cannot reach the SignalWalk server (${err.message}).`; return; }
  $("plan-name").textContent = state.plan.name;
  const badge = $("mode-badge"); badge.hidden = false;
  const real = state.cfg.mode === "real";
  badge.textContent = real ? "Real Wi-Fi readings" : "Simulation: virtual house";
  badge.className = "badge" + (real ? " real" : "");
  $("hint").textContent = real
    ? "Stand still at a spot, click that spot on the plan, and keep the laptop steady for about 2 seconds. Cover every room, including corners."
    : "Simulation mode: click anywhere on the plan to 'measure' a virtual laptop standing there, or press Auto-survey. Nothing is read from your real Wi-Fi.";
  if (!real) $("btn-auto").hidden = false;
  drawLegend();

  $("map").addEventListener("click", (ev) => { const [x, y] = pointerToMeters(ev); measureAt(x, y); });
  $("map").addEventListener("mousemove", onHover);
  $("map").addEventListener("mouseleave", () => { $("tooltip").hidden = true; });
  $("opt-confidence").addEventListener("change", (e) => { state.showConfidence = e.target.checked; drawMap(); });
  $("opt-advice").addEventListener("change", (e) => { state.showAdvice = e.target.checked; drawMap(); });
  $("btn-auto").addEventListener("click", async () => {
    try { const r = await post("/api/sim/auto-survey", { count: 10 }); toast(`Added ${r.added} simulated measurements.`); await refresh(); } catch (err) { toast(err.message); }
  });
  $("btn-undo").addEventListener("click", () => { if (state.points.length) removePoint(state.points.length - 1); });
  $("btn-reset").addEventListener("click", async () => {
    if (state.points.length && !window.confirm("Delete all measurements?")) return;
    try { await post("/api/reset"); await refresh(); } catch (err) { toast(err.message); }
  });
  window.addEventListener("resize", drawMap);
  await refresh();
}

init();
