// Evolve progress page: reads sample/<run>.json (schema evolve-progress-v1) and draws the evolved
// arm beside the no-selection arm and the no-card floor. Anything it cannot honor is shown as an
// error: a curve drawn without its control proves nothing. No network beyond the local file.
// URL option: ?run=evolve-dry-run
(() => {
  "use strict";

  const SCHEMA = "evolve-progress-v1";
  const LABELS = ["exploratory", "scored"];
  const ARMS = {
    evolved: { text: "Evolved (under test)", color: "#7cc4ff" },
    no_selection: { text: "No selection, equal compute (reference)", color: "#f0a35e" },
  };
  const FLOOR_COLOR = "#9aa2b5";
  const W = 640, H = 260, PAD = 36;
  const $ = (id) => document.getElementById(id);
  const fail = (msg) => { throw new Error(msg); };

  function svgEl(tag, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  }

  function check(doc) {
    if (doc.schema !== SCHEMA) fail(`unknown schema ${doc.schema}`);
    if (typeof doc.dry_run !== "boolean") fail("dry_run is missing: refusing to say what this is");
    if (/^dry run/i.test(doc.label) && !doc.dry_run) fail("a dry-run label without dry_run: refusing");
    if (!doc.spend || typeof doc.spend.calls !== "number") fail("no ledger spend in the file");
    if (!LABELS.includes(doc.claim)) fail(`claim ${doc.claim} is neither exploratory nor scored`);
    for (const arm of Object.keys(ARMS)) {
      if (!doc.curves.some((p) => p.arm === arm)) fail(`no curve for the ${arm} arm: refusing to draw`);
    }
    if (!doc.floor) fail("no no-card floor: refusing to draw");
    for (const p of [...doc.curves, ...doc.validation, doc.floor]) {
      if (!LABELS.includes(p.label)) fail("a point has no label");
    }
  }

  function scale(doc) {
    const values = [...doc.curves.map((p) => p.mean_fitness), doc.floor.mean_fitness];
    const last = Math.max(...doc.curves.map((p) => p.generation), 1);
    const low = Math.min(0, ...values), high = Math.max(...values) * 1.1 || 1;
    return {
      x: (g) => PAD + (g / last) * (W - 2 * PAD),
      y: (v) => H - PAD - ((v - low) / (high - low)) * (H - 2 * PAD),
      last,
    };
  }

  function drawCurves(doc) {
    const svg = $("curves"), at = scale(doc);
    svg.append(svgEl("line", { x1: PAD, y1: H - PAD, x2: W - PAD, y2: H - PAD, class: "axis" }));
    for (let g = 0; g <= at.last; g += 1) {
      const t = svgEl("text", { x: at.x(g), y: H - 12, "text-anchor": "middle" });
      t.textContent = `gen ${g}`;
      svg.append(t);
    }
    const floorY = at.y(doc.floor.mean_fitness);
    svg.append(svgEl("line", { x1: PAD, y1: floorY, x2: W - PAD, y2: floorY, stroke: FLOOR_COLOR, "stroke-dasharray": "5 4", "stroke-width": 2 }));
    for (const [arm, style] of Object.entries(ARMS)) {
      const points = doc.curves.filter((p) => p.arm === arm).sort((a, b) => a.generation - b.generation);
      const path = points.map((p) => `${at.x(p.generation)},${at.y(p.mean_fitness)}`).join(" ");
      svg.append(svgEl("polyline", { points: path, fill: "none", stroke: style.color, "stroke-width": 3 }));
    }
  }

  function addLegend(doc) {
    const entries = [
      ...Object.values(ARMS).map((s) => [s.text, s.color]),
      [`No card (floor), ${doc.floor.mean_fitness.toFixed(3)}`, FLOOR_COLOR],
    ];
    for (const [text, color] of entries) {
      const li = document.createElement("li");
      li.style.setProperty("--sw", color);
      li.textContent = text;
      $("legend").append(li);
    }
  }

  function addRows(listId, lines) {
    for (const line of lines) {
      const li = document.createElement("li");
      li.textContent = line;
      $(listId).append(li);
    }
  }

  function render(doc) {
    const prefix = doc.dry_run ? "SIMULATED, NOT A RESULT: " : "";
    $("banner").textContent = `${prefix}${doc.label} | claim: ${doc.claim} | Spark: ${doc.spend.calls} calls, ${doc.spend.dollars} dollars (${doc.spend.source})`;
    if (doc.dry_run) {
      document.body.classList.add("simulated");
      document.title = `SIMULATED ${document.title}`;
      $("curves").append(svgEl("text", { x: W / 2, y: 20, "text-anchor": "middle", class: "stamp" }));
      $("curves").lastChild.textContent = "SIMULATED: a dry run, not a result";
    }
    drawCurves(doc);
    addLegend(doc);
    addRows("gap", doc.validation.map((v) => `gen ${v.generation}: training ${v.training_mean.toFixed(3)}, validation ${v.validation_mean.toFixed(3)}, gap ${v.gap.toFixed(3)} (${v.label})`));
    const dropped = doc.ungraded.reduce((sum, p) => sum + p.dropped_cases, 0);
    addRows("guards", [
      `noise check: ${doc.noise ? doc.noise.verdict : "not run"}`,
      `cases dropped for ungraded games: ${dropped}`,
      `stop: ${doc.stop_reason || "none, the run finished"}`,
    ]);
    addRows("tree", doc.family_tree.map((n) => `${n.card_id} gen ${n.generation} ${n.operator}${n.parents.length ? " from " + n.parents.join(" + ") : ""}`));
    $("page").hidden = false;
  }

  const run = new URLSearchParams(location.search).get("run") || "evolve-dry-run";
  fetch(`sample/${encodeURIComponent(run)}.json`)
    .then((response) => (response.ok ? response.json() : fail(`cannot load ${run}.json`)))
    .then((doc) => { check(doc); render(doc); })
    .catch((error) => { $("error").textContent = error.message; $("error").hidden = false; });
})();
