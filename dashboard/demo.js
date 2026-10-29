// Demo page: replays two coding runs (plain and personal Glimmer) side by side from
// sample/<replay>.json (schema demo-replay-v1) and shows the measured headlines from
// sample/demo-headlines.json (demo-headlines-v1). No network beyond those local files.
// URL options: ?replay=demo-replay  &autoplay=0  &speed=0.5|1|2  &step=N (1-based)
// Anything the page cannot honor is shown as an error, never silently replaced: a demo that
// quietly patched a broken replay would film a result nobody measured.
(() => {
  "use strict";

  const REPLAY_SCHEMA = "demo-replay-v1";
  const HEADLINE_SCHEMA = "demo-headlines-v1";
  const ROLES = ["floor", "ceiling", "reference", "under test"];
  const STATUSES = ["measured", "established", "hypothesis"];
  const ROUTE_A_REPLAY = "Route A offline replay";
  // What each source is called on a note card; a source not listed shows as itself.
  const SOURCE_LABELS = { [ROUTE_A_REPLAY]: "Route A note (offline replay of a real run; the coding model did not see these notes)" };
  const NOTE_SOURCES = ["classifier fired", "Glimmer recalled", "lesson in prompt (pilot)", ROUTE_A_REPLAY];
  const SPEEDS = [0.5, 1, 2];
  const BASE_MS = 1600; // one step per 1.6 s at 1x: long enough to read a note aloud
  const RUN_COLORS = { plain: "#9a6b1f", personal: "#1d5fa8" };

  const $ = (id) => document.getElementById(id);
  const fmt = (n) => Math.round(n).toLocaleString("en-US");
  const fail = (msg) => { throw new Error(msg); };
  const state = { replay: null, headlines: null, cur: 0, timer: null, speed: 1 };

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  const svgEl = (tag, attrs) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  };
  const tagEl = (status) => el("span", `tag ${status}`, `[${status}]`);
  const roleEl = (role) => el("span", `role ${role.replace(" ", "-")}`, role);

  // ---- contract: the cross-field rules a JSON schema cannot state ----

  function checkRunShape(run) {
    if (!run.subtitle) fail(`Run ${run.id} carries no subtitle.`);
    if (run.runs_solved > run.runs_total) fail(`Run ${run.id}: the record says ${run.runs_solved} of ${run.runs_total} solved.`);
    if (run.runs_solved === 0 && run.totals.result === "solved") fail(`Run ${run.id}: shown as solved but the record has no solved run.`);
    if (!ROLES.includes(run.role)) fail(`Run ${run.id} has no valid role label (floor, ceiling, reference, under test).`);
    if (!STATUSES.includes(run.status)) fail(`Run ${run.id} has no claim tag.`);
    run.steps.forEach((s, i) => {
      if (s.step !== i + 1) fail(`Run ${run.id}: step ${i + 1} is numbered ${s.step}.`);
      if (s.note && !NOTE_SOURCES.includes(s.note.source)) fail(`Run ${run.id} step ${s.step}: a note must say where it came from.`);
      if (s.classifier && s.classifier.who !== "logistic classifier") fail(`Run ${run.id} step ${s.step}: the speak decision belongs to the logistic classifier.`);
      if (s.picker && (s.picker.who !== "our network" || "speak" in s.picker)) fail(`Run ${run.id} step ${s.step}: the network picks an adapter; it never decides to speak.`);
    });
  }

  // A plain run that received notes is not a floor any more: the comparison would be fake.
  function checkPlainIsPlain(run) {
    if (run.id !== "plain") return;
    if (run.adapter !== null) fail("The plain run names an adapter; it must run without one.");
    if (run.steps.some((s) => s.note || s.classifier || s.picker)) fail("The plain run received notes or decisions; it must run without the symbiont.");
  }

  function checkTotals(run) {
    const t = run.totals, st = run.steps;
    const sum = (f) => st.reduce((a, s) => a + f(s), 0);
    const expect = {
      steps: st.length, tokens_in: sum((s) => s.tokens_in), tokens_out: sum((s) => s.tokens_out),
      repeated_mistakes: sum((s) => (s.mistake_tag === "repeated" ? 1 : 0)), new_mistakes: sum((s) => (s.mistake_tag === "new" ? 1 : 0)),
      wasted_steps: sum((s) => (s.wasted ? 1 : 0)), notes: sum((s) => (s.note ? 1 : 0)),
    };
    for (const [k, v] of Object.entries(expect)) {
      if (t[k] !== v) fail(`Run ${run.id}: totals.${k} is ${t[k]} but the steps add up to ${v}.`);
    }
    if (Math.abs(t.wall_s - sum((s) => s.wall_s)) > 0.05) fail(`Run ${run.id}: totals.wall_s disagrees with the steps.`);
  }

  function checkReplay(d) {
    if (d.schema !== REPLAY_SCHEMA) fail(`Expected schema ${REPLAY_SCHEMA}, got ${d.schema}.`);
    if (!STATUSES.includes(d.status)) fail("The replay has no claim tag.");
    const ids = (d.runs || []).map((r) => r.id);
    if (ids.length !== 2 || ids[0] !== "plain" || ids[1] !== "personal") fail("The replay needs exactly two runs: plain, then personal.");
    for (const run of d.runs) { checkRunShape(run); checkPlainIsPlain(run); checkTotals(run); }
  }

  // A fly row alone would make the fly look like the whole story: counters sit beside it.
  function checkHeadlines(h) {
    if (h.schema !== HEADLINE_SCHEMA) fail(`Expected schema ${HEADLINE_SCHEMA}, got ${h.schema}.`);
    for (const line of h.headlines) {
      if (!STATUSES.includes(line.status)) fail(`Headline ${line.id} has no claim tag.`);
      if (!/^results\/[a-z0-9-]+\.json/.test(line.source)) fail(`Headline ${line.id} does not name its results file.`);
      const labels = line.rows.map((r) => r.label);
      line.rows.forEach((r, i) => {
        if (!ROLES.includes(r.role)) fail(`Headline ${line.id} row ${r.label} has no valid role label.`);
        if (r.label.startsWith("fly") && labels[i - 1] !== "counters" && labels[i + 1] !== "counters") fail(`Headline ${line.id}: the counters row must sit directly beside ${r.label}.`);
      });
    }
  }

  // ---- runs ----

  const maxSteps = () => Math.max(...state.replay.runs.map((r) => r.steps.length));
  const seenSteps = (run, cur) => run.steps.slice(0, cur + 1);

  function runHeader(run) {
    const head = el("div", "run-title");
    const h = el("h2", "", run.label);
    h.id = `h-${run.id}`;
    head.append(h, roleEl(run.role), tagEl(run.status));
    const sub = el("p", "run-sub", run.subtitle);
    const record = el("p", "run-record", `On this task: ${run.runs_solved} of ${run.runs_total} runs solved. Showing run ${run.shown_run} (${run.totals.result}).`);
    return [head, sub, record];
  }

  function tallyBlock(repeats, stepsUsed) {
    const box = el("div", "tally");
    box.append(el("div", `tally-n${repeats ? " has-repeats" : ""}`, String(repeats)));
    const label = el("div", "tally-label", (repeats === 1 ? "repeated mistake" : "repeated mistakes") + ` in ${stepsUsed} ${stepsUsed === 1 ? "step" : "steps"}`);
    const marks = el("div", "tally-marks");
    for (let i = 0; i < repeats; i++) marks.append(el("i", "", "✕"));
    label.append(marks);
    box.append(label);
    return box;
  }

  function statsBlock(seen) {
    const sum = (f) => seen.reduce((a, s) => a + f(s), 0);
    const box = el("div", "stats");
    const items = [
      [sum((s) => (s.wasted ? 1 : 0)), "wasted steps"],
      [sum((s) => (s.mistake_tag === "new" ? 1 : 0)), "new mistakes"],
      [fmt(sum((s) => s.tokens_in)), "tokens read"],
      [fmt(sum((s) => s.tokens_out)), "tokens written"],
    ];
    for (const [v, label] of items) {
      const stat = el("div", "stat");
      stat.append(el("b", "", String(v)), el("span", "", label));
      box.append(stat);
    }
    return box;
  }

  function stepRow(s, isCurrent) {
    const li = el("li", [s.mistake_tag === "repeated" ? "repeat" : "", isCurrent ? "current" : ""].join(" ").trim());
    const action = el("span", "", s.action);
    if (s.mistake_tag === "repeated") action.append(el("span", "flag repeated", "✕ repeat"));
    if (s.mistake_tag === "new") action.append(el("span", "flag new", "new mistake"));
    if (s.note) action.append(el("span", "flag delivered", "note"));
    if (s.outcome === "solved") action.append(el("span", "flag solved", "solved"));
    li.append(el("span", "n", String(s.step)), action, el("span", "tok", `${fmt(s.tokens_in)} in, ${fmt(s.tokens_out)} out`));
    if (isCurrent) li.setAttribute("aria-current", "step");
    return li;
  }

  function renderRun(run, cur) {
    const seen = seenSteps(run, cur);
    const list = el("ol", "steps");
    seen.forEach((s, i) => list.append(stepRow(s, i === cur)));
    const box = $(`run-${run.id}`);
    box.replaceChildren(...runHeader(run), tallyBlock(seen.filter((s) => s.mistake_tag === "repeated").length, seen.length), statsBlock(seen), list);
    if (cur >= run.steps.length - 1) box.append(el("p", "finished", `Finished at step ${run.steps.length}: ${run.totals.result}.`));
  }

  // ---- token chart: one axis (tokens read), one line per run, direct labels ----

  const CHART = { w: 1000, h: 230, left: 70, right: 150, top: 14, bottom: 34 };

  function chartScales() {
    const n = maxSteps();
    const cum = state.replay.runs.map((r) => r.steps.reduce((a, s) => [...a, (a.at(-1) || 0) + s.tokens_in], []));
    const top = Math.max(...cum.map((c) => c.at(-1)));
    const x = (i) => CHART.left + (i * (CHART.w - CHART.left - CHART.right)) / Math.max(1, n - 1);
    const y = (v) => CHART.h - CHART.bottom - (v * (CHART.h - CHART.top - CHART.bottom)) / top;
    return { n, cum, top, x, y };
  }

  function chartAxes(svg, sc) {
    for (let k = 0; k <= 4; k++) {
      const v = (sc.top * k) / 4, yy = sc.y(v);
      svg.append(svgEl("line", { class: "grid", x1: CHART.left, x2: CHART.w - CHART.right, y1: yy, y2: yy }));
      svg.append(Object.assign(svgEl("text", { class: "axis", x: CHART.left - 10, y: yy + 5, "text-anchor": "end" }), { textContent: `${Math.round(v / 1000)}k` }));
    }
    for (let i = 0; i < sc.n; i++) {
      svg.append(Object.assign(svgEl("text", { class: "axis", x: sc.x(i), y: CHART.h - 8, "text-anchor": "middle" }), { textContent: String(i + 1) }));
    }
  }

  // Direct labels at each line's end; two labels closer than LABEL_GAP are pushed apart so
  // they never print over each other while the lines still run close together.
  const LABEL_GAP = 22;
  function endLabels(ends) {
    const ys = ends.map((e) => e.y + 5);
    if (Math.abs(ys[0] - ys[1]) < LABEL_GAP) {
      const mid = (ys[0] + ys[1]) / 2, upper = ys[0] <= ys[1] ? 0 : 1;
      ys[upper] = mid - LABEL_GAP / 2;
      ys[1 - upper] = mid + LABEL_GAP / 2;
    }
    return ys;
  }

  function chartLines(svg, sc, cur) {
    const ends = state.replay.runs.map((run, r) => {
      const pts = sc.cum[r].slice(0, cur + 1);
      const color = RUN_COLORS[run.id];
      svg.append(svgEl("path", { class: "line", stroke: color, d: pts.map((v, i) => `${i ? "L" : "M"}${sc.x(i).toFixed(1)},${sc.y(v).toFixed(1)}`).join("") }));
      const last = pts.length - 1;
      svg.append(svgEl("circle", { class: "dot", fill: color, cx: sc.x(last), cy: sc.y(pts[last]), r: 6 }));
      return { x: sc.x(last), y: sc.y(pts[last]), text: `${run.label} ${Math.round(pts[last] / 1000)}k` };
    });
    endLabels(ends).forEach((y, k) => {
      svg.append(Object.assign(svgEl("text", { class: "end-label", x: ends[k].x + 12, y }), { textContent: ends[k].text }));
    });
  }

  function showTip(sc, i) {
    const tip = $("token-tip");
    const parts = state.replay.runs.map((run, r) => (i < run.steps.length ? `${run.label} ${fmt(sc.cum[r][i])}` : `${run.label} finished`));
    tip.textContent = `Step ${i + 1}: ${parts.join(", ")} read`;
    tip.style.left = `${(100 * sc.x(i)) / CHART.w}%`;
    tip.hidden = false;
  }

  function renderTokens(cur) {
    const svg = $("token-chart"), sc = chartScales();
    svg.replaceChildren();
    chartAxes(svg, sc);
    svg.append(svgEl("line", { class: "cursor", x1: sc.x(cur), x2: sc.x(cur), y1: CHART.top, y2: CHART.h - CHART.bottom }));
    chartLines(svg, sc, cur);
    const band = (CHART.w - CHART.left - CHART.right) / Math.max(1, sc.n - 1);
    for (let i = 0; i < sc.n; i++) {
      const hit = svgEl("rect", { class: "hit", x: sc.x(i) - band / 2, y: 0, width: band, height: CHART.h });
      hit.addEventListener("pointerenter", () => showTip(sc, i));
      hit.addEventListener("pointerleave", () => { $("token-tip").hidden = true; });
      svg.append(hit);
    }
    const totals = state.replay.runs.map((r, k) => `${r.label} ${fmt(sc.cum[k][Math.min(cur, r.steps.length - 1)])}`);
    svg.setAttribute("aria-label", `Cumulative tokens read at step ${cur + 1}: ${totals.join(", ")}`);
  }

  // ---- notes and brain (personal run only: the plain run has neither by contract) ----

  function noteItem(s, latest) {
    const li = el("li", `note${latest ? " latest" : ""}`);
    const head = el("div", "note-head");
    const kind = { "Glimmer recalled": "recalled", "lesson in prompt (pilot)": "prompt" }[s.note.source] || "classifier";
    head.append(el("b", "", `Step ${s.step}`), el("span", `source ${kind}`, SOURCE_LABELS[s.note.source] || s.note.source));
    const dl = el("dl");
    const check = el("dd");
    check.append(el("code", "", s.note.check));
    dl.append(el("dt", "", "What happened"), el("dd", "", s.note.what), el("dt", "", "How it was resolved"), el("dd", "", s.note.resolved), el("dt", "", "Check to run"), check);
    li.append(head, dl);
    return li;
  }

  function renderNotes(cur) {
    const withNotes = seenSteps(state.replay.runs[1], cur).filter((s) => s.note);
    const items = withNotes.map((s, i) => noteItem(s, i === withNotes.length - 1 && s.step === cur + 1));
    $("note-stream").replaceChildren(...(items.length ? items : [el("li", "empty", "No notes yet. Each note appears at the step it was delivered.")]));
  }

  // Past the run's last step there is no decision to show: repeating the last verdict
  // would claim the classifier is still deciding for a run that has ended.
  function classifierVerdict(run, cur) {
    if (cur >= run.steps.length) return [el("p", "verdict quiet", "Finished"), el("p", "reason", `The run ended at step ${run.steps.length}: ${run.totals.result}.`)];
    const step = run.steps[cur];
    if (!step.classifier) return [el("p", "off", "Not running at this step.")];
    const speak = step.classifier.speak === "speak";
    return [el("p", `verdict ${speak ? "speak" : "quiet"}`, speak ? "Speak" : "Stay quiet"), el("p", "reason", step.classifier.reason)];
  }

  function classifierBlock(run, cur) {
    const box = el("div", "decider");
    const head = el("div", "decider-head");
    head.append(el("b", "", "logistic classifier"), el("span", "", "decides whether to speak"));
    box.append(head);
    box.append(...classifierVerdict(run, cur));
    const hist = el("div", "history");
    hist.setAttribute("aria-hidden", "true");
    seenSteps(run, cur).forEach((s, i) => hist.append(el("i", [s.classifier && s.classifier.speak === "speak" ? "speak" : "", i === cur ? "current" : ""].join(" ").trim())));
    box.append(hist);
    return box;
  }

  function pickerBlock(run, cur) {
    const box = el("div", "decider");
    const head = el("div", "decider-head");
    head.append(el("b", "", "our network"), el("span", "", "picks the adapter"));
    box.append(head);
    const pick = seenSteps(run, cur).filter((s) => s.picker).at(-1);
    if (!pick) {
      box.append(el("p", "off", run.adapter ? "No pick yet." : "Not used in this run."));
      return box;
    }
    box.append(el("p", "verdict quiet", pick.picker.adapter), el("p", "reason", `Step ${pick.step}: ${pick.picker.reason}`));
    return box;
  }

  function renderBrain(cur) {
    const run = state.replay.runs[1];
    const plainNote = el("p", "off", "Plain Glimmer: nothing decides and nothing speaks.");
    const classifierUsed = run.steps.some((s) => s.classifier);
    const classifierPanel = classifierUsed ? classifierBlock(run, cur) : el("p", "off", "Classifier not used in this replay.");
    $("brain").replaceChildren(classifierPanel, pickerBlock(run, cur), plainNote);
  }

  // ---- results strip ----

  function headlineCard(line) {
    const card = el("article", "headline");
    const title = el("h3", "", line.label);
    title.append(" ", tagEl(line.status));
    const table = el("table");
    for (const r of line.rows) {
      const tr = el("tr");
      const name = el("td", "", r.label);
      name.append(" ", roleEl(r.role));
      const ci = r.ci95_low === null ? "" : `[${r.ci95_low.toFixed(3)}, ${r.ci95_high.toFixed(3)}]`;
      tr.append(name, el("td", "num", r.value.toFixed(3)), el("td", "ci", ci));
      table.append(tr);
    }
    card.append(title, el("p", "verdict-line", `${line.unit}; ${line.verdict}`), table, el("p", "verdict-line", line.note), el("p", "src", line.source));
    return card;
  }

  // ---- replay loop ----

  function render() {
    const cur = state.cur, n = maxSteps();
    state.replay.runs.forEach((run) => renderRun(run, cur));
    renderTokens(cur);
    renderNotes(cur);
    renderBrain(cur);
    $("scrub").max = n - 1;
    $("scrub").value = cur;
    $("step-out").textContent = `Step ${cur + 1} of ${n}`;
  }

  function buildStatic() {
    const d = state.replay;
    $("task-label").textContent = d.task.label;
    $("task-id").textContent = `${d.task.repo}, ${d.task.id}`;
    $("banner").textContent = `Replay [${d.status}]: ${d.source}`;
    for (const id of ["tokens-tag", "notes-tag", "brain-tag"]) $(id).replaceChildren(tagEl(d.status));
    $("headlines").replaceChildren(...state.headlines.headlines.map(headlineCard));
    $("results-source").textContent = state.headlines.source;
  }

  function setPlaying(on) {
    clearInterval(state.timer);
    state.timer = null;
    $("play").textContent = on ? "Pause" : "Play";
    if (!on) return;
    state.timer = setInterval(() => {
      if (state.cur >= maxSteps() - 1) return setPlaying(false);
      state.cur += 1;
      render();
    }, BASE_MS / state.speed);
  }

  function showError(message) {
    setPlaying(false);
    $("page").hidden = true;
    $("error").textContent = message;
    $("error").hidden = false;
  }

  async function fetchJson(name) {
    const res = await fetch(`sample/${name}.json`);
    if (!res.ok) fail(`Could not load sample/${name}.json (${res.status}). Serve the dashboard folder over http.`);
    return res.json();
  }

  function readOptions(q) {
    const replay = q.get("replay") ?? "demo-replay";
    if (!/^[a-z0-9-]+$/.test(replay)) fail(`replay="${replay}" must be a file name under sample/, without .json.`);
    const speed = q.has("speed") ? Number(q.get("speed")) : 1;
    if (!SPEEDS.includes(speed)) fail(`Unsupported speed "${q.get("speed")}". Use one of ${SPEEDS.join(", ")}.`);
    const step = q.has("step") ? Number(q.get("step")) : 1;
    return { replay, speed, step, autoplay: q.get("autoplay") !== "0", hook: q.get("hook") !== "0" };
  }

  async function start() {
    try {
      const o = readOptions(new URLSearchParams(location.search));
      const [replay, headlines] = await Promise.all([fetchJson(o.replay), fetchJson("demo-headlines")]);
      checkReplay(replay);
      checkHeadlines(headlines);
      Object.assign(state, { replay, headlines, speed: o.speed });
      if (!Number.isInteger(o.step) || o.step < 1 || o.step > maxSteps()) fail(`step=${o.step} is outside this replay (1 to ${maxSteps()}).`);
      state.cur = o.step - 1;
      $("speed").value = String(o.speed);
      $("hook").hidden = !o.hook;
      $("page").hidden = false;
      buildStatic();
      render();
      setPlaying(o.autoplay);
    } catch (e) {
      showError(e.message);
    }
  }

  function wireControls() {
    $("play").addEventListener("click", () => {
      if (!state.replay) return;
      if (!state.timer && state.cur >= maxSteps() - 1) state.cur = 0;
      setPlaying(!state.timer);
      render();
    });
    $("restart").addEventListener("click", () => { if (!state.replay) return; state.cur = 0; render(); setPlaying(true); });
    $("speed").addEventListener("change", (e) => { state.speed = Number(e.target.value); if (state.timer) setPlaying(true); });
    $("scrub").addEventListener("input", (e) => { setPlaying(false); state.cur = Number(e.target.value); render(); });
  }

  wireControls();
  start();
})();
