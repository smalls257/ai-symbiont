// Dashboard page. Reads one JSON produced by export_dashboard (schema dashboard-v0)
// and replays it step by step. No network beyond the local sample file.
// URL options: ?act=freedoom|coding  &autoplay=0  &speed=0.5|1|2|4  &step=12
// Anything the page cannot honour is shown as an error, never silently replaced.
"use strict";

const SCHEMA = "dashboard-v0";
const ROLES = ["floor", "ceiling", "reference", "under test"];
const STATUSES = ["measured", "established", "hypothesis"];
const SPEEDS = [0.5, 1, 2, 4];
const BASE_MS = 700;
const COLS = 130;
const ROLE_COLORS = { floor: "#8d96ad", ceiling: "#7bd88f", reference: "#f0a35e", "under test": "#7cc4ff" };
const ACT_TEXT = {
  freedoom: { label: "Act 1: Freedoom", faults: "Level fault map" },
  coding: { label: "Act 2: a developer's week", faults: "Repo fault map" },
};

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
};
const fmt = (n) => n.toLocaleString("en-US");

const state = { data: null, cur: 0, timer: null, speed: 1, pulseAt: 0, lastPulsed: -1 };

const fail = (msg) => { throw new Error(msg); };

// A race or scoreboard with the fly alone would make the fly look like the whole
// story, so the page refuses to draw it: the counters entry must sit directly beside it.
function checkBeside(kind, keys) {
  if (!keys.includes("fly")) return;
  if (!keys.includes("counters")) fail(`The ${kind}s are missing the counters ${kind}; it must sit beside the fly ${kind}.`);
  if (Math.abs(keys.indexOf("fly") - keys.indexOf("counters")) !== 1) fail(`The counters ${kind} must sit directly beside the fly ${kind}.`);
}

function checkLabelled(kind, item) {
  if (!ROLES.includes(item.role)) fail(`The ${kind} ${item.key ?? item.id} has no valid role label.`);
  if (!STATUSES.includes(item.status)) fail(`The ${kind} ${item.key ?? item.id} has no claim tag (measured, established or hypothesis).`);
}

function checkContract(d) {
  if (d.schema !== SCHEMA) fail(`Expected schema ${SCHEMA}, got ${d.schema}.`);
  if (!ACT_TEXT[d.act]) fail(`Unknown act "${d.act}".`);
  if (!d.lanes?.length) fail("The replay has no sessions.");
  if (!d.fault_map?.length) fail("The replay has no fault map entries.");
  if (!d.scoreboard?.length) fail("The replay has no scoreboard.");
  const keys = d.scoreboard.map((r) => r.key);
  for (const k of ["counters", "fly"]) {
    if (!keys.includes(k)) fail(`Scoreboard is missing the ${k} row; the counters row must sit beside the fly row.`);
  }
  checkBeside("row", keys);
  checkBeside("lane", d.lanes.map((l) => l.id));
  d.scoreboard.forEach((r) => checkLabelled("row", r));
  d.lanes.forEach((l) => checkLabelled("lane", l));
  for (const k of ["fault_map", "brain"]) {
    if (!STATUSES.includes(d.panel_status?.[k])) fail(`The ${k} panel has no claim tag.`);
  }
  if (d.brain.steps.length !== stepsOf(d)) fail(`The brain has ${d.brain.steps.length} steps but the session has ${stepsOf(d)}; refusing to show a stale brain.`);
}

const tagEl = (status) => {
  const el = document.createElement("span");
  el.className = `tag ${status}`;
  el.textContent = `[${status}]`;
  return el;
};
const roleEl = (role) => {
  const el = document.createElement("span");
  el.className = `role ${role.replace(" ", "-")}`;
  el.textContent = role;
  return el;
};
// Lane title: name, role label and claim tag, so no arm is shown unlabelled.
const laneTitle = (lane) => {
  const el = document.createElement("span");
  el.className = "ltitle";
  const name = document.createElement("b");
  name.textContent = lane.label;
  el.append(name, " ", roleEl(lane.role), " ", tagEl(lane.status));
  return el;
};

function stepsOf(d) { return Math.max(...d.lanes.map((l) => l.events.length)); }

function buildStatic(d) {
  const text = ACT_TEXT[d.act];
  $("act-label").textContent = text.label;
  $("faults-tag").replaceChildren(tagEl(d.panel_status.fault_map));
  $("cells-tag").replaceChildren(tagEl("established"));
  $("source").textContent = d.source || "";
  document.querySelector("[data-act-text=faults]").textContent = text.faults;
  for (const b of document.querySelectorAll(".seg button")) b.setAttribute("aria-pressed", String(b.dataset.act === d.act));
  $("cells-n").textContent = fmt(d.brain.cells);
  $("brain").setAttribute("aria-label", `${fmt(d.brain.cells)} cells, ${fmt(d.brain.active_per_step)} active this step`);
  $("active-n").textContent = fmt(d.brain.active_per_step);

  const max = Math.max(...d.fault_map.map((f) => f.pain_points));
  $("faults").replaceChildren(...d.fault_map.map((f) => {
    const row = document.createElement("div");
    row.className = "fault";
    row.innerHTML = '<span class="p"></span><span class="bar-bg"><span class="heat" style="display:block"></span></span><span class="n"></span>';
    row.querySelector(".p").textContent = f.path;
    row.querySelector(".p").title = f.path;
    row.querySelector(".heat").style.width = `${(100 * f.pain_points) / max}%`;
    row.querySelector(".n").textContent = f.pain_points;
    return row;
  }));
}

function renderTimelines(d, cur) {
  const n = stepsOf(d);
  const W = Math.max(400, Math.round($("timelines").clientWidth || 1000));
  const x = (i) => 10 + (i * (W - 20)) / Math.max(1, n - 1);
  $("timelines").replaceChildren(...d.lanes.map((lane) => {
    const color = ROLE_COLORS[lane.role];
    const seen = lane.events.filter((e) => e.t <= cur);
    const repeats = seen.filter((e) => e.repeat).length;
    const box = document.createElement("div");
    box.className = "lane";
    box.innerHTML = `<div class="lane-head"><span class="slot"></span><span class="count"></span></div>`;
    box.querySelector(".slot").replaceChildren(laneTitle(lane));
    box.querySelector(".count").innerHTML = `${seen.length} steps, <em>${repeats} repeats</em>`;
    const s = svg("svg", { class: "track", viewBox: `0 0 ${W} 40`, role: "img", "aria-label": `${lane.label}: ${seen.length} steps, ${repeats} repeats` });
    s.append(svg("line", { class: "rail", x1: 10, x2: W - 10, y1: 26, y2: 26 }));
    for (const e of seen) {
      const t = svg("line", { class: "tick", x1: x(e.t), x2: x(e.t), y1: 19, y2: 33, stroke: e.repeat ? "#ff6b6b" : color });
      s.append(t);
      if (e.repeat) s.append(svg("circle", { class: "mark", cx: x(e.t), cy: 9, r: 4.5 }));
    }
    s.append(svg("line", { class: "head", x1: x(cur), x2: x(cur), y1: 1, y2: 39 }));
    box.append(s);
    return box;
  }));
}

function fuelAt(lane, cur) {
  let last = { tokens: 0, dollars: 0 };
  for (const f of lane.fuel) if (f.t <= cur) last = f;
  return last;
}

function renderGauges(d, cur) {
  const maxTok = Math.max(...d.lanes.map((l) => l.totals.tokens), 1);
  const maxUsd = Math.max(...d.lanes.map((l) => l.totals.dollars), 1e-9);
  const bar = (name, v, max, text, color) => {
    const row = document.createElement("div");
    row.className = "gauge-row";
    row.innerHTML = '<span class="nm"></span><span class="bar-bg"><span class="bar-fill"></span></span><span class="val"></span>';
    row.querySelector(".nm").textContent = name;
    const fill = row.querySelector(".bar-fill");
    fill.style.width = `${(100 * v) / max}%`;
    fill.style.background = color;
    row.querySelector(".val").textContent = text;
    return row;
  };
  $("gauges").replaceChildren(...d.lanes.map((lane) => {
    const f = fuelAt(lane, cur), color = ROLE_COLORS[lane.role];
    const g = document.createElement("div");
    g.className = "gauge";
    g.append(laneTitle(lane), bar("tokens", f.tokens, maxTok, fmt(Math.round(f.tokens)), color), bar("dollars", f.dollars, maxUsd, `$${f.dollars.toFixed(2)}`, color));
    return g;
  }));
}

function renderSpirals(d, cur) {
  $("spirals").replaceChildren(...d.lanes.map((lane) => {
    const wrap = document.createElement("div");
    wrap.className = "spiral";
    const s = svg("svg", { viewBox: "-110 -110 220 220", role: "img", "aria-label": `${lane.label} loop spiral` });
    const pt = (i) => [(6 + i * 2) * Math.cos(i * 0.6), (6 + i * 2) * Math.sin(i * 0.6)];
    const seen = lane.events.filter((e) => e.t <= cur);
    if (seen.length > 1) s.append(svg("path", { class: "trace", d: "M" + seen.map((e) => pt(e.t).map((v) => v.toFixed(1)).join(",")).join("L") }));
    for (const e of seen) {
      const [cx, cy] = pt(e.t);
      s.append(svg("circle", { class: e.repeat ? "rep-dot" : "step-dot", ...(e.repeat ? {} : { fill: ROLE_COLORS[lane.role] }), cx: cx.toFixed(1), cy: cy.toFixed(1), r: e.repeat ? 4.5 : 2.4 }));
    }
    wrap.append(s);
    const cap = document.createElement("div");
    cap.append(laneTitle(lane), ` ${seen.filter((e) => e.repeat).length} repeats`);
    wrap.append(cap);
    return wrap;
  }));
}

function renderBrain(d, cur) {
  const cv = $("brain"), ctx = cv.getContext("2d");
  const rows = Math.ceil(d.brain.cells / COLS);
  const cw = cv.width / COLS, ch = cv.height / rows, r = Math.min(cw, ch) * 0.36;
  const steps = d.brain.steps;
  const now = steps[cur];
  const prev = cur > 0 ? steps[cur - 1] : null;
  const cell = (i) => [(i % COLS + 0.5) * cw, (Math.floor(i / COLS) + 0.5) * ch];
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = "#1a1f2d";
  for (let i = 0; i < d.brain.cells; i++) { const [x, y] = cell(i); ctx.fillRect(x - r, y - r, 2 * r, 2 * r); }
  const paint = (cells, color, k) => { ctx.fillStyle = color; for (const i of cells) { const [x, y] = cell(i); ctx.fillRect(x - r * k, y - r * k, 2 * r * k, 2 * r * k); } };
  if (prev) paint(prev.active, "#2b4a66", 1.15);
  paint(now.active, now.learned ? "#f0a35e" : "#7cc4ff", 1.45);
  const flag = $("learn-flag");
  flag.classList.toggle("on", now.learned);
  flag.replaceChildren(now.learned ? "learn event: dopamine pulse " : "no learn event ", tagEl(d.panel_status.brain));
}

// Dopamine pulse: a ring that sweeps outward from the middle of the grid.
function pulseFrame(now) {
  const k = (now - state.pulseAt) / 900;
  renderBrain(state.data, state.cur);
  if (k < 0 || k >= 1) return;
  const cv = $("brain"), ctx = cv.getContext("2d");
  ctx.strokeStyle = `rgba(240,163,94,${0.85 * (1 - k)})`;
  ctx.lineWidth = 8 * (1 - k) + 1;
  ctx.beginPath();
  ctx.arc(cv.width / 2, cv.height / 2, k * cv.width * 0.55, 0, 2 * Math.PI);
  ctx.stroke();
  requestAnimationFrame(pulseFrame);
}

function renderScoreboard(d, cur) {
  const final = cur >= stepsOf(d) - 1;
  const body = $("scoreboard").querySelector("tbody");
  body.replaceChildren(...d.scoreboard.map((r) => {
    const tr = document.createElement("tr");
    if (r.key === "fly") tr.className = "fly";
    tr.innerHTML = `<td></td><td></td><td></td><td class="num ${final ? "" : "pending"}"></td>`;
    tr.children[0].textContent = r.label;
    tr.children[1].append(roleEl(r.role));
    tr.children[2].append(tagEl(r.status));
    tr.children[3].textContent = final ? r.value : "shown at the end";
    return tr;
  }));
}

function render() {
  const d = state.data, cur = state.cur, n = stepsOf(d);
  renderTimelines(d, cur);
  renderGauges(d, cur);
  renderSpirals(d, cur);
  renderBrain(d, cur);
  renderScoreboard(d, cur);
  $("scrub").max = n - 1;
  $("scrub").value = cur;
  $("step-out").textContent = `step ${cur + 1} / ${n}`;
  const learned = d.brain.steps[cur].learned;
  if (learned && cur !== state.lastPulsed && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    state.lastPulsed = cur;
    state.pulseAt = performance.now();
    requestAnimationFrame(pulseFrame);
  }
}

function setPlaying(on) {
  clearInterval(state.timer);
  state.timer = null;
  $("play").textContent = on ? "Pause" : "Play";
  if (!on) return;
  state.timer = setInterval(() => {
    if (state.cur >= stepsOf(state.data) - 1) return setPlaying(false);
    state.cur += 1;
    render();
  }, BASE_MS / state.speed);
}

function showError(message) {
  $("grid").hidden = true;
  setPlaying(false);
  $("error").textContent = message;
  $("error").hidden = false;
}

async function load(act, opts = {}) {
  $("error").hidden = true;
  try {
    const res = await fetch(`sample/${act}.json`);
    if (!res.ok) fail(`Could not load sample/${act}.json (${res.status}). Serve the dashboard folder over http.`);
    const d = await res.json();
    checkContract(d);
    const step = opts.step ?? 0;
    if (!Number.isInteger(step) || step < 0 || step >= stepsOf(d)) fail(`step=${step} is outside this replay (0 to ${stepsOf(d) - 1}).`);
    state.data = d;
    state.cur = step;
    $("grid").hidden = false;
    buildStatic(d);
    render();
    setPlaying(opts.autoplay !== false);
  } catch (e) {
    showError(e.message);
  }
}

// Reads one URL option; returns null when absent, throws when present but unusable.
function readOptions(q) {
  const act = q.get("act") ?? "freedoom";
  if (!ACT_TEXT[act]) fail(`Unknown act "${act}". Use act=freedoom or act=coding.`);
  const speed = q.has("speed") ? Number(q.get("speed")) : 1;
  if (!SPEEDS.includes(speed)) fail(`Unsupported speed "${q.get("speed")}". Use one of ${SPEEDS.join(", ")}.`);
  const step = q.has("step") ? Number(q.get("step")) : 0;
  return { act, speed, step };
}

function init() {
  for (const b of document.querySelectorAll(".seg button")) b.addEventListener("click", () => load(b.dataset.act));
  $("play").addEventListener("click", () => {
    if (!state.data) return;
    if (!state.timer && state.cur >= stepsOf(state.data) - 1) state.cur = 0;
    setPlaying(!state.timer);
    render();
  });
  $("restart").addEventListener("click", () => { if (!state.data) return; state.cur = 0; render(); setPlaying(true); });
  $("speed").addEventListener("change", (e) => { state.speed = Number(e.target.value); if (state.timer) setPlaying(true); });
  $("scrub").addEventListener("input", (e) => { setPlaying(false); state.cur = Number(e.target.value); render(); });
  const q = new URLSearchParams(location.search);
  try {
    const o = readOptions(q);
    state.speed = o.speed;
    $("speed").value = String(o.speed);
    load(o.act, { autoplay: q.get("autoplay") !== "0", step: o.step });
  } catch (e) {
    showError(e.message);
  }
}
init();
