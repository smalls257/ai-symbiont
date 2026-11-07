// Draws the Topics page and the Inbox topic panel with synthetic data and prints what a developer would see.
// Run by test_topics_page.py: `node topics_harness.js <static dir>`.
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const replaced = [];
const document = {
  getElementById: () => null,
  createElement: () => ({ style: {}, setAttribute() {}, appendChild() {} }),
  head: { appendChild() {} },
  body: { appendChild() {} },
  addEventListener() {},
};
const history = { replaceState: (_s, _t, url) => replaced.push(url) };
const sandbox = { window: {}, document, history, CSS: { escape: (s) => s }, innerWidth: 1280, innerHeight: 800, URL, URLSearchParams, console };
for (const file of ["tip.js", "rename.js", "inbox_model.js", "topics_parts.js", "topics.js"]) {
  vm.runInNewContext(fs.readFileSync(path.join(process.argv[2], file), "utf8"), sandbox);
}
const render = sandbox.window.SymbiontTopics.render;

const outcomes = (done, partly, stuck) => ({ done, partly, stuck, unclear: 0 });
const session = (id, goal, outcome, friction) => ({ id, date: "2026-03-09", goal, outcome, friction });
const topic = (key, sessions, done, over) => ({
  key, name: key, description: "about " + key, sessions, outcomes: outcomes(done, sessions - done, 0),
  first: "2026-03-02", last: "2026-03-16", perWeek: [sessions, 0, 1], examples: ["goal one", "goal two", "goal three"],
  frictions: { slow: 1 }, incidents: 0,
  sessionList: Array.from({ length: sessions }, (_, i) => session("s" + i, "goal " + i, i < done ? "done" : "partly", i ? "" : "a slow test")), ...over,
});
const view = (topics, over) => ({
  ready: true, sessions: 40, noiseSessions: 4, undated: 0, months: [], weeks: ["2026-W10", "2026-W11", "2026-W12"],
  allPerWeek: [10, 20, 10], requests: 3, frictions: [{ name: "slow", description: "slow things", sessions: 8 }], topics, ...over,
});
const card = (topic, noise) => ({ topic, noise: noise || null });
const group = (key, name, kind, cards, over) => ({ key, name, kind, cards, noise: false, ...over });

const container = () => {
  const box = { innerHTML: "", classList: { add() {} }, addEventListener() {}, onclick: null, querySelector: () => null };
  const click = (match) => box.onclick({ target: { closest: (sel) => (match[sel] ? { dataset: match[sel] } : null) } });
  return Object.assign(box, { click });
};
const draw = (tv, options) => {
  const box = container();
  const page = render(box, tv, { compact: false, project: "p", ...options });
  return { box, page };
};

const topics = [topic("Parser work", 6, 5), topic("Slow CI", 4, 1), topic("Docs", 9, 3), topic("One-off", 1, 1)];
const groups = [
  group("g1", "pytest fails", "failure", [card("Slow CI"), card("Slow CI"), card("Slow CI"), card("Docs"), card("Slow CI", "noise")]),
  group("g2", "You said no", "correction", [card("Slow CI"), card("Slow CI")]),
  group("g3", "noisy", "failure", [card("Slow CI")], { noise: true }),
  ...Array.from({ length: 9 }, (_, i) => group("x" + i, "extra " + i, "failure", [card("Slow CI")])),
];
const rowOrder = (html) => [...html.matchAll(/class="trow pick[^"]*" data-topic="([^"]+)"/g)].map((m) => m[1]);

const main = draw(view(topics), { groups, triage: {} });
const hard = draw(view(topics), { groups, triage: {} });
hard.box.click({ "[data-sort]": { sort: "hard" } });
const picked = draw(view(topics), { groups, triage: {} });
picked.box.click({ "[data-topic]": { topic: "Slow CI" } });
const select = draw(view(topics), { groups, triage: {} });
select.page.select("Slow CI");

console.log(JSON.stringify({
  main: main.box.innerHTML,
  mainOrder: rowOrder(main.box.innerHTML),
  hardOrder: rowOrder(hard.box.innerHTML),
  hardHtml: hard.box.innerHTML,
  pickedUrl: replaced[replaced.length - 1],
  pickedHtml: picked.box.innerHTML,
  selected: select.box.innerHTML,
  asked: draw(view(topics), { t: "Slow CI", groups, triage: {} }).box.innerHTML,
  unknown: draw(view(topics), { t: "Nope <b>", groups, triage: {} }).box.innerHTML,
  noRequests: draw(view(topics, { requests: null }), {}).box.innerHTML,
  renamed: draw(view(topics), { groups, triage: { g1: { name: "Renamed group" } } }).box.innerHTML,
  compact: draw(view(topics), { compact: true }).box.innerHTML,
  compactOpen: (() => {
    const box = container();
    render(box, view(topics), { compact: true, project: "p" });
    box.onclick({ target: { closest: (sel) => (sel === "[data-fold]" ? { dataset: { fold: "Docs" } } : null) } });
    return box.innerHTML;
  })(),
  hostile: draw(view([topic("<img src=x onerror=1>", 3, 1, { sessionList: [session("<s>", "<b>g</b>", "done", "<i>f</i>")] }), topics[0]]), {
    t: "<img src=x onerror=1>",
    groups: [group("<k>", "<u>grp</u>", "failure", [card("<img src=x onerror=1>")])],
  }).box.innerHTML,
}));
