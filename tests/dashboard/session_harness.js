// Runs the session page's model and renderer under node and prints plain values for test_session.py.
// `node session_harness.js <static dir>`
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const HOSTILE = "<img src=x onerror=window.__x=1>";
const pane = () => ({ innerHTML: "", onclick: null, onchange: null, querySelectorAll: () => [], querySelector: () => null });
const crumbs = [];
const navigated = [];
const sandbox = {
  window: {}, document: { getElementById: () => null, addEventListener() {} }, URL, URLSearchParams, console,
  fetch: async () => { throw new Error("no fetch set"); },
};
sandbox.window.SymbiontViews = { registerDetail(view, fn) { sandbox.registered = [view, fn]; }, setCrumb: (t) => crumbs.push(t), navigate: (r) => navigated.push(r) };
for (const file of ["tip.js", "inbox_model.js", "session_model.js", "session_parts.js", "session.js"]) {
  vm.runInNewContext(fs.readFileSync(path.join(process.argv[2], file), "utf8"), sandbox);
}
const W = sandbox.window;
const Model = W.SymbiontSessionModel;

// The snapshot is built by the real emitters (incident_groups, topic_view._session); see test_session.py.
const snapshot = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const groups = snapshot.incidents.groups;
const data = snapshot;
const realCard = groups[0].cards[0];
const cardCount = groups.reduce((n, g) => n + g.cards.length, 0);
const table = Model.joinOf(groups);
const tags = [["s1", 3], ["s1", 7], ["s1", 4], ["s2", 1], ["s2", 2]].map(([id, step]) => Model.tagOf(table, id, step));
const withoutStep = groups.map((g) => ({ ...g, cards: g.cards.map(({ step, ...rest }) => rest) }));
const noStepData = { incidents: { groups: withoutStep } };
const many = { incidents: { groups: [{ key: "g", name: "g", cards: Array.from({ length: 60 }, (_, i) => ({ ...realCard, sessionId: "s" + i })) }] } };
const tagFor = (step) => Model.tagOf(table, "s1", step);
const failed = [{ step: 3 }, { step: 4 }, { step: 7 }];
const messages = [{ step: 3 }, { step: 4 }];

const body = (over) => ({
  goal: "Fix the parser", date: "2026-03-09", minutes: 41, total: 5000, shown: 600,
  steps: [[0, "you", "you"], [3, "failed", "pytest tests/x"], [4, "edit", "src/a.py"], [5, "failed", "ls nothing"], [7, "failed", "ls"], [9, "you", "you"]],
  messages: [{ step: 0, text: "please fix it", before: null, then: "pytest tests/x" }, { step: 9, text: HOSTILE, before: "ls", then: null }],
  failed: [{ step: 3, command: "pytest tests/x", error: "ImportError: x" }, { step: 5, command: HOSTILE, error: "boom" }, { step: 7, command: "ls", error: "no" }],
  counts: { steps: 5000, failed: 41, edits: 1, scratch: 0, messages: 9, passed: 40 }, shownCounts: { steps: 600, failed: 3, edits: 1, scratch: 0, messages: 2, passed: 40 }, outcome: "done", friction: "Imports kept breaking.", ...over,
});
const reply = (status, json) => ({ ok: status < 400, status, json: async () => json });

async function drawn(route, answer) {
  const p = pane();
  sandbox.fetch = async (url) => { sandbox.lastUrl = url; return typeof answer === "function" ? answer() : answer; };
  const render = W.SymbiontSession.render;
  const pending = render(p, route, data, "my repo");
  const loading = p.innerHTML;
  await pending;
  return { p, loading, html: p.innerHTML, url: sandbox.lastUrl };
}

(async () => {
  const ok = await drawn({ view: "session", id: "s1", step: 3 }, reply(200, body()));
  const clickFilter = (value) => ok.p.onclick({ target: { closest: (sel) => (sel === "[data-filter]" ? { dataset: { filter: value }, } : null) } });
  clickFilter("messages:group");
  const afterGroupFilter = ok.p.innerHTML;
  clickFilter("failed:quiet");
  const afterQuiet = ok.p.innerHTML;
  ok.p.onchange({ target: { matches: () => true, value: "s2" } });
  const missing = await drawn({ view: "session", id: "zz" }, reply(404, { error: "no such session" }));
  const gone = await drawn({ view: "session", id: "s1" }, reply(404, { error: "this session's log is no longer readable" }));
  const refused = await drawn({ view: "session", id: "s1" }, reply(400, { error: "unknown project 'x'" }));
  const down = await drawn({ view: "session", id: "s1" }, () => { throw new Error("connection refused"); });
  const capped = ok.html;
  const small = await drawn({ view: "session", id: "s1" }, reply(200, body({ total: 6, shown: 6 })));
  const unsummarized = await drawn({ view: "session", id: "s2" }, reply(200, body()));
  const plainNotFound = await drawn({ view: "session", id: "s1" }, { ok: false, status: 404, json: async () => { throw new Error("not json"); } });
  const oddLane = await drawn({ view: "session", id: "s1" }, reply(200, body({ steps: [[0, "weird", "x"], [3, "failed", "pytest"]], minutes: "41" })));
  const outside = await drawn({ view: "session", id: "s1", step: 4000 }, reply(200, body()));
  console.log(JSON.stringify({
    registered: sandbox.registered && sandbox.registered[0], tags, ids: ["s1\u0000x"].length,
    stepless: Model.joinOf(noStepData.incidents.groups).size, joined: table.size, cardCount,
    picker: Model.pickerOf(data, "s1"), pickerOther: Model.pickerOf(data, "nope").currentListed, capped40: Model.pickerOf(many, "s0").rows.length,
    keptMessages: Model.keptMessages(messages, tagFor, "group").map((m) => m.step), keptAll: Model.keptMessages(messages, tagFor, "all").length,
    keptFailed: Model.keptFailed(failed, tagFor, "quiet").map((f) => f.step), noise: Model.noiseCount(failed, tagFor),
    capText: Model.capText(600, 5000), capNone: Model.capText(6, 6), wall: [Model.activeTime(41), Model.activeTime(120), Model.activeTime(null)],
    loading: ok.loading, url: ok.url, html: capped, unsummarized: unsummarized.html, plainNotFound: plainNotFound.html, oddLane: oddLane.html, small: small.html, outside: outside.html,
    afterGroupFilter, afterQuiet, navigated, crumbs, missing: missing.html, gone: gone.html, refused: refused.html, down: down.html,
  }));
})();
