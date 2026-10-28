// ai-symbiont explainer: vanilla JS, no network, no frameworks.
// Four small machines: the depth dial, a mushroom-body bench, a net-benefit bench, a label-window
// stepper, and a gate catalog filter. Every number the benches show is either computed live from
// the same rule the source uses, or copied from results/*.json (counts and labels only).
(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  // ---------- depth dial: one control opens every fold up to the chosen level ----------
  function applyDepth(level) {
    $$("details.deeper").forEach((d) => { d.open = Number(d.dataset.level) <= level; });
    document.body.dataset.depth = String(level);
    try { localStorage.setItem("symbiont-depth", String(level)); } catch (e) { /* storage may be off */ }
  }
  const dial = $$("input[name=depth]");
  if (dial.length) {
    let saved = 1;
    try { saved = Number(localStorage.getItem("symbiont-depth")) || 1; } catch (e) { saved = 1; }
    const match = dial.find((i) => Number(i.value) === saved);
    if (match) match.checked = true;
    applyDepth(saved);
    dial.forEach((i) => i.addEventListener("change", () => applyDepth(Number(i.value))));
  }
  // Deep links into a closed fold open it.
  function openFoldFor(hash) {
    if (!hash) return;
    const target = document.getElementById(hash.slice(1));
    if (!target) return;
    let node = target;
    while (node) { if (node.tagName === "DETAILS") node.open = true; node = node.parentElement; }
  }
  window.addEventListener("hashchange", () => openFoldFor(location.hash));
  openFoldFor(location.hash);

  // ---------- reading progress and current section in the table of contents ----------
  const bar = $("#progress");
  function progress() {
    const h = document.documentElement;
    const max = h.scrollHeight - h.clientHeight;
    if (bar) bar.style.width = (max > 0 ? (100 * h.scrollTop) / max : 0) + "%";
  }
  window.addEventListener("scroll", progress, { passive: true });
  progress();
  const tocLinks = $$(".toc a");
  if ("IntersectionObserver" in window && tocLinks.length) {
    const byId = new Map(tocLinks.map((a) => [a.getAttribute("href").slice(1), a]));
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        tocLinks.forEach((a) => a.removeAttribute("aria-current"));
        const a = byId.get(en.target.id);
        if (a) a.setAttribute("aria-current", "true");
      });
    }, { rootMargin: "-20% 0px -70% 0px" });
    byId.forEach((_, id) => { const s = document.getElementById(id); if (s) io.observe(s); });
  }

  // ---------- the mushroom-body bench ----------
  // The same rule as src/symbiont/core/mushroom.py, at the fly's published counts: 86 inputs,
  // 5,177 Kenyon cells, 7 inputs per cell, the top 5% fire (259), one output weight per cell.
  // Trouble followed: the active cells' weights are cut by the learning rate. Calm: they relax
  // back at a tenth of that strength. Warn when the mean active weight is under the threshold.
  const N_IN = 86, N_KC = 5177, K = 7, N_ACTIVE = 259, LR = 0.1, RELAX = 0.1, THRESHOLD = 0.5;
  function rng(seed) { // mulberry32: small, deterministic, good enough for a picture
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const flyCanvas = $("#fly-canvas");
  if (flyCanvas) {
    const r = rng(20261029);
    const wiring = new Int16Array(N_KC * K);
    for (let i = 0; i < wiring.length; i++) wiring[i] = Math.floor(r() * N_IN);
    const jitter = new Float32Array(N_KC);
    for (let i = 0; i < N_KC; i++) jitter[i] = r() * 1e-3;
    function pattern(seed, ones) {
      const x = new Float32Array(N_IN), rr = rng(seed);
      let placed = 0;
      while (placed < ones) { const j = Math.floor(rr() * N_IN); if (!x[j]) { x[j] = 1; placed++; } }
      return x;
    }
    // B shares most of A's inputs (same file, similar command); C is unrelated work.
    const A = pattern(11, 20);
    const B = new Float32Array(A); { const rr = rng(12); let moved = 0; for (let j = 0; j < N_IN && moved < 5; j++) if (B[j]) { B[j] = 0; let k; do { k = Math.floor(rr() * N_IN); } while (B[k] || A[k]); B[k] = 1; moved++; } }
    const C = pattern(13, 20);
    const steps = { A, B, C };
    let w = new Float32Array(N_KC).fill(1);
    let current = "A";
    let history = [];
    function activeCells(x) {
      const act = new Float32Array(N_KC);
      for (let c = 0; c < N_KC; c++) { let s = jitter[c]; for (let k = 0; k < K; k++) s += x[wiring[c * K + k]]; act[c] = s; }
      const idx = Array.from({ length: N_KC }, (_, i) => i);
      idx.sort((p, q) => act[q] - act[p]);
      return idx.slice(0, N_ACTIVE);
    }
    const ctx = flyCanvas.getContext("2d");
    const COLS = 72, CELL = flyCanvas.width / COLS;
    const style = getComputedStyle(document.documentElement);
    function color(weight) { // 1 = untouched (paper), 0 = pushed all the way down (amber)
      const depth = 1 - weight;
      return `rgba(181, 84, 27, ${0.08 + 0.92 * depth})`;
    }
    function draw(active) {
      ctx.clearRect(0, 0, flyCanvas.width, flyCanvas.height);
      const activeSet = new Set(active);
      for (let c = 0; c < N_KC; c++) {
        const x = (c % COLS) * CELL, y = Math.floor(c / COLS) * CELL;
        ctx.fillStyle = color(w[c]);
        ctx.fillRect(x + 1, y + 1, CELL - 2, CELL - 2);
        if (activeSet.has(c)) { ctx.strokeStyle = style.getPropertyValue("--ink").trim() || "#000"; ctx.lineWidth = 1.5; ctx.strokeRect(x + 1.5, y + 1.5, CELL - 3, CELL - 3); }
      }
    }
    function overlapWith(name) {
      const a = new Set(activeCells(steps[current])), b = activeCells(steps[name]);
      return b.filter((c) => a.has(c)).length;
    }
    function render() {
      const active = activeCells(steps[current]);
      let sum = 0; for (const c of active) sum += w[c];
      const score = sum / N_ACTIVE, risk = 1 - score;
      draw(active);
      $("#fly-score").textContent = score.toFixed(3);
      $("#fly-risk").textContent = risk.toFixed(3);
      $("#fly-meter span").style.width = (100 * risk) + "%";
      const verdict = $("#fly-verdict");
      const warn = score < THRESHOLD - 1e-9;
      verdict.textContent = warn ? "would warn: this step looks like past trouble" : "stays quiet: this step looks like nothing that went wrong before";
      verdict.className = "verdict " + (warn ? "warn" : "quiet");
      $("#fly-overlap").textContent = ["A", "B", "C"].map((n) => `${n}: ${overlapWith(n)}`).join("   ");
      $("#fly-log").textContent = history.length ? history.slice(-6).join("\n") : "no outcomes yet";
      $$("[data-step]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.step === current)));
    }
    $$("[data-step]").forEach((b) => b.addEventListener("click", () => { current = b.dataset.step; render(); }));
    $("#btn-trouble").addEventListener("click", () => {
      for (const c of activeCells(steps[current])) w[c] *= 1 - LR;
      history.push(`step ${current}: trouble followed, active weights cut by ${LR}`);
      render();
    });
    $("#btn-calm").addEventListener("click", () => {
      for (const c of activeCells(steps[current])) w[c] += LR * (1 - w[c]) * RELAX;
      history.push(`step ${current}: nothing went wrong, active weights relax a tenth as fast`);
      render();
    });
    $("#btn-reset").addEventListener("click", () => { w = new Float32Array(N_KC).fill(1); history = []; render(); });
    render();
  }

  // ---------- the net-benefit bench: measured precision and flag rate, an assumed cost ----------
  // Rows copied from results/warning-budget-exploratory.json (test split, 82 tasks). Net benefit per
  // 100 steps = 100 * (TP - c * FP) / steps = 100 * flag_rate * (precision - c * (1 - precision)).
  const NB_ROWS = {
    "0.1":  { counters: { p: 0.1719, f: 0.1778 }, fly: { p: 0.2297, f: 0.0869 } },
    "0.15": { counters: { p: 0.1709, f: 0.2290 }, fly: { p: 0.2309, f: 0.1339 } },
    "0.2":  { counters: { p: 0.1731, f: 0.2516 }, fly: { p: 0.2304, f: 0.1848 } },
  };
  const FLOOR = { p: 0.1521, f: 1.0 };
  const costInput = $("#nb-cost");
  if (costInput) {
    const AXIS = 80; // bars are scaled to plus or minus this many points per 100 steps
    function nb(row, c) { return 100 * row.f * (row.p - c * (1 - row.p)); }
    function renderNb() {
      const c = Number(costInput.value);
      const budget = ($("input[name=budget]:checked") || {}).value || "0.15";
      const rows = NB_ROWS[budget];
      $("#nb-cost-out").textContent = c.toFixed(2);
      $("#nb-breakeven").textContent = (c / (1 + c)).toFixed(2);
      const items = [
        ["warn on every step (floor)", nb(FLOOR, c), "floor"],
        ["counters (reference)", nb(rows.counters, c), "counters"],
        ["fly (under test)", nb(rows.fly, c), "fly"],
        ["stay silent (floor)", 0, "floor"],
      ];
      $("#nb-bars").innerHTML = items.map(([label, v, cls]) => {
        const pct = Math.max(-AXIS, Math.min(AXIS, v)) / AXIS * 50;
        const left = pct < 0 ? 50 + pct : 50, width = Math.abs(pct);
        return `<div class="bar ${cls}"><span>${label}</span><div class="track" role="img" aria-label="${label}: ${v.toFixed(1)} per 100 steps"><div class="fill" style="left:${left}%;width:${width}%"></div></div><span class="val">${v >= 0 ? "+" : ""}${v.toFixed(1)}</span></div>`;
      }).join("");
      const best = Math.max(rows.counters.p, rows.fly.p);
      $("#nb-reading").textContent = best > c / (1 + c)
        ? "At this cost a warning pays: the best measured precision is above break-even."
        : `At this cost no measured row pays: break-even needs precision above ${(c / (1 + c)).toFixed(2)} and the best measured is ${best.toFixed(2)}. Staying silent wins on these recorded steps.`;
    }
    costInput.addEventListener("input", renderNb);
    $$("input[name=budget]").forEach((i) => i.addEventListener("change", renderNb));
    renderNb();
  }

  // ---------- the label-window stepper ----------
  // A synthetic 12-step session. Pain points sit at steps 8 and 11. A step is labeled "trouble
  // ahead" when a pain point falls within the next 5 steps, the same window the replay scores on.
  const stepBox = $("#steps");
  if (stepBox) {
    const PAIN = new Set([8, 11]), WINDOW = 5, N = 12;
    const kinds = ["read", "edit", "test", "edit", "test", "edit", "read", "test", "edit", "test", "edit", "test"];
    let chosen = 4;
    function labelOf(t) { for (let d = 1; d <= WINDOW; d++) if (PAIN.has(t + d)) return t + d; return null; }
    function renderSteps() {
      stepBox.innerHTML = "";
      const ahead = labelOf(chosen);
      for (let t = 1; t <= N; t++) {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = String(t);
        b.setAttribute("aria-pressed", String(t === chosen));
        b.setAttribute("aria-label", `step ${t}, ${kinds[t - 1]}${PAIN.has(t) ? ", pain point" : ""}`);
        if (PAIN.has(t)) b.classList.add("pain");
        if (t > chosen && t <= chosen + WINDOW) b.classList.add("window");
        b.addEventListener("click", () => { chosen = t; renderSteps(); });
        stepBox.appendChild(b);
      }
      const seen = [...PAIN].filter((p) => p < chosen);
      $("#step-out").innerHTML =
        `<b>Step ${chosen}</b> (${kinds[chosen - 1]}). Label: <b>${ahead ? `trouble ahead, a pain point lands at step ${ahead}` : "calm, nothing in the next five steps"}</b>. ` +
        `What the learner may see: the session so far (steps 1 to ${chosen}) and pain points from <em>earlier</em> sessions. ` +
        `Pain points of this session (${seen.length ? "even step " + seen.join(" and ") + ", already behind us" : "none yet"}) are hidden until the session ends, because they are placed after the fact.`;
    }
    renderSteps();
  }

  // ---------- gate catalog filter ----------
  const filters = $$(".filters button");
  if (filters.length) {
    function applyFilter(v) {
      filters.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === v)));
      $$(".gates li").forEach((li) => { li.hidden = v !== "all" && !li.dataset.v.split(" ").includes(v); });
      const n = $$(".gates li:not([hidden])").length;
      $("#gate-count").textContent = `${n} gate famil${n === 1 ? "y" : "ies"} shown`;
    }
    filters.forEach((b) => b.addEventListener("click", () => applyFilter(b.dataset.v)));
    applyFilter("all");
  }

})();
