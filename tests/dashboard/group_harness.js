// Runs the group page's model and renderer under node with a fake pane and a fake fetch; prints plain values.
// `node group_harness.js <static dir> <snapshot.json>` (the snapshot is built by the real emitters in test_group.py).
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const HOSTILE = "<img src=x onerror=window.__x=1>";
const calls = [];
const sandbox = { setTimeout() {}, clearTimeout() {}, window: {}, document: { getElementById: () => null, addEventListener() {} }, URL, URLSearchParams, console, fetch: null };
const crumbs = [];
const navigated = [];
sandbox.window.SymbiontViews = { registerDetail(view, fn) { sandbox.registered = view; }, setCrumb: (t) => crumbs.push(t), navigate: (r) => navigated.push(r) };
sandbox.fetch = async (url, init) => {
  calls.push([url, JSON.parse(init.body)]);
  if (url === "/lessons/add") return { ok: true, status: 200, text: async () => JSON.stringify({ added: 1, ids: ["lesson-9"] }) };
  if (url === "/triage") return { ok: true, status: 200, text: async () => JSON.stringify({ state: init.body.includes("archived") ? "archived" : "reviewed", taught_on: "2026-11-02", name: "" }) };
  return { ok: false, status: 500, text: async () => "boom" };
};
for (const file of ["tip.js", "rename.js", "inbox_model.js", "inbox_rows.js", "inbox_dialogs.js", "triage_actions.js", "group_model.js", "group_parts.js", "group.js"]) {
  vm.runInNewContext(fs.readFileSync(path.join(process.argv[2], file), "utf8"), sandbox);
}
const W = sandbox.window;
const base = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const clone = (o) => JSON.parse(JSON.stringify(o));

function fakePane() {
  const nodes = {};
  const focused = [];
  const pane = {
    onclick: null, onchange: null, oninput: null, focused, nodes,
    appendChild() {}, querySelectorAll: () => [],
    set innerHTML(html) { this.html = html; },
    get innerHTML() { return this.html || ""; },
    querySelector(sel) {
      if (!nodes[sel]) {
        const node = { innerHTML: "", textContent: "", disabled: false, classes: [], scrolled: 0, dataset: {},
          classList: { add: (c) => node.classes.push(c) }, scrollIntoView() { node.scrolled++; }, focus() { focused.push(sel); } };
        const field = (id, re) => ({ get() { const m = re.exec(nodes["#gTeach"].innerHTML); return node.typed !== undefined ? node.typed : (m ? m[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">") : ""); }, set(v) { node.typed = v; } });
        if (sel === "#gWhen") Object.defineProperty(node, "value", field(sel, /id="gWhen" value="([^"]*)"/));
        if (sel === "#gWhat") Object.defineProperty(node, "value", field(sel, /<textarea id="gWhat"[^>]*>([^<]*)<\/textarea>/));
        nodes[sel] = node;
      }
      return nodes[sel];
    },
  };
  return pane;
}
const flush = () => new Promise((r) => setTimeout(r, 0));
const click = (pane, matches) => pane.onclick({ target: { closest: (sel) => matches[sel] || null } });
const text = (pane, sel) => pane.nodes[sel].innerHTML;
const all = (pane) => Object.values(pane.nodes).map((n) => n.innerHTML).join("\n") + pane.html;

function show(data, key, hash) {
  const pane = fakePane();
  W.SymbiontGroup.render(pane, { view: "group", key, hash }, data, "my repo");
  return pane;
}
const failureKey = base.incidents.groups.find((g) => g.kind === "failure" && g.times > 20).key;
const corrKey = base.incidents.groups.find((g) => g.kind === "correction").key;
const triaged = (extra) => { const d = clone(base); d.triage = { [failureKey]: extra }; return d; };

(async () => {
  const main = show(clone(base), failureKey);
  const firstPage = text(main, "#gList");
  const nav = (id) => click(main, { "[data-occ]": { dataset: { occ: id } } });
  nav("older"); const secondPage = text(main, "#gList"), secondNav = text(main, "#gNav");
  nav("first"); const firstJump = text(main, "#gList"), firstNav = text(main, "#gNav");
  nav("latest"); const latestJump = text(main, "#gList");
  nav("clearest"); const clearestJump = text(main, "#gList");
  const newerAtStart = (() => { nav("latest"); return text(main, "#gNav"); })();

  const taught = show(triaged({ state: "archived", regressed: false, taught_on: "2026-10-12", name: "", changed_on: "2026-10-20", return_rule: "until_worse" }), failureKey);
  const quiet = show(clone(base), failureKey);
  const regress = show(triaged({ state: "for_review", regressed: true, taught_on: null, name: "", changed_on: "2026-10-03", return_rule: null }), failureKey);
  const hostile = show(triaged({ state: "for_review", regressed: false, taught_on: null, name: HOSTILE, changed_on: "2026-10-03", return_rule: null }), failureKey);
  const hostileKey = show(clone(base), HOSTILE);
  const missing = show(clone(base), "nope");
  const crumbsAfter = crumbs.slice();
  const corr = show(clone(base), corrKey);
  const noOwn = clone(base); noOwn.incidents.ownHistory = false;
  const corrDataset = show(noOwn, corrKey);
  const teachHash = show(clone(base), failureKey, "teach");

  // actions: mark reviewed, archive, taught
  const act = show(clone(base), failureKey);
  click(act, { "button[data-a]": { dataset: { a: "reviewed" } } });
  await flush();
  const reviewedCalls = calls.splice(0);
  act.onchange({ target: { matches: () => true, value: "0" } });
  await flush();
  const archiveCalls = calls.splice(0);
  act.nodes["#gWhat"].value = "Run uv sync first.";
  act.oninput({ target: { matches: () => true } });
  const preview = text(act, "#gPreview");
  click(act, { "[data-save]": {} });
  await flush();
  const saveCalls = calls.splice(0);
  const savedLabel = act.nodes["#gSave"].textContent;
  const reviewButton = show(clone(base), failureKey);
  click(reviewButton, { "button[data-a]": { dataset: { a: "teach" } } });

  console.log(JSON.stringify({
    registered: sandbox.registered, firstPage, secondPage, secondNav, firstJump, firstNav, latestJump, clearestJump, newerAtStart,
    head: text(main, "#gHead"), timeline: text(main, "#gTimeline"), three: text(main, "#gThree"), teach: text(main, "#gTeach"), preview: text(main, "#gPreview"),
    topics: text(main, "#gTopics"), others: text(main, "#gOthers"), activityQuiet: text(quiet, "#gAct"), activityTaught: text(taught, "#gAct"),
    headTaught: text(taught, "#gHead"), timelineTaught: text(taught, "#gTimeline"), teachTaught: text(taught, "#gTeach"), activityRegress: text(regress, "#gAct"), headRegress: text(regress, "#gHead"),
    hostile: all(hostile), hostileKey: hostileKey.html, missing: missing.html, crumbs: crumbsAfter, corr: all(corr), corrDataset: all(corrDataset),
    teachHash: [teachHash.nodes["#gTeach"].scrolled, teachHash.nodes["#gTeach"].classes, teachHash.focused],
    plainFocus: [reviewButton.nodes["#gTeach"].scrolled, reviewButton.focused],
    reviewedCalls, archiveCalls, saveCalls, preview, savedLabel, actHead: text(act, "#gHead"),
    model: { pick: W.SymbiontGroupModel.clearest([{ fixed: "", command: "x" }, { fixed: "Edited a.py", command: "y".repeat(120) }, { fixed: "Edited b.py", command: "z" }, { fixed: "Edited c.py", command: "w" }]),
      pages: [1, 12, 13, 30].map(W.SymbiontGroupModel.pagesOf), pageOf: [0, 17, 18, 29].map((i) => W.SymbiontGroupModel.pageOfIndex(30, i)),
      cut: W.SymbiontGroupModel.noteText("mistake", "Word. ".repeat(200)).length,
      house: W.SymbiontGroupModel.noteText("correction", "Use uv. "), repo: W.SymbiontGroupModel.noteText("mistake", "Run uv sync first ") },
  }));
})();
