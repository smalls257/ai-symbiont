// Renders topics.js and trends.js into a bare container and prints the markup they build.
// Run by test_views.py: `node views_harness.js <static dir>`.
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const node = () => ({ id: "", style: {}, setAttribute() {}, appendChild() {}, classList: { add() {} } });
const document = {
  getElementById: () => ({}),
  createElement: node,
  head: { appendChild() {} },
  body: { appendChild() {} },
  addEventListener() {},
};
const sandbox = { window: {}, document, innerWidth: 1280, innerHeight: 800, URL, URLSearchParams, console };
sandbox.window.addEventListener = () => {};
for (const file of ["tip.js", "rename.js", "inbox_model.js", "topics.js", "trends_side.js", "trends.js", "views.js"]) {
  vm.runInNewContext(fs.readFileSync(path.join(process.argv[2], file), "utf8"), sandbox);
}
const container = () => ({ innerHTML: "", classList: { add() {} }, addEventListener() {}, onclick: null });
const draw = (render, ...args) => {
  const box = container();
  render(box, ...args);
  return box.innerHTML;
};
const T = sandbox.window.SymbiontTopics.render;
const R = (box, data) => sandbox.window.SymbiontTrends.render(box, data, "my proj");
const HOSTILE = "<img src=x onerror=window.__x=1>";

const sessionsByDate = [
  { id: "a", date: "2026-03-09", goal: "Fix the parser", outcome: null },
  { id: "b", date: null, goal: "Older work", outcome: null },
];
const notReady = (extra) => ({ ready: false, needed: 25, sessions: 0, topics: [], sessionsByDate, ...extra });
const topic = (name) => ({
  key: name, name, description: "d", sessions: 2, outcomes: { done: 2, partly: 0, stuck: 0, unclear: 0 },
  first: "2026-03-01", last: "2026-03-09", perMonth: [2], frictions: {}, incidents: 0, sessionList: [],
});
const ready = { ready: true, needed: 0, sessions: 2, undated: 0, months: ["2026-03"], frictions: [], topics: [topic(HOSTILE)], sessionsByDate: [] };

const cell = (times, sessions) => ({ times, sessions, per10: sessions ? (10 * times) / sessions : null });
const row = (over) => ({
  key: "g", title: "pytest failing with ImportError", kind: "failure", last: "2026-03-09", trend: "steady",
  undatedTimes: 0, outsideTimes: 0, cells: [cell(1, 10)], taught: null, ...over,
});
const trends = (over) => ({ months: [{ month: "2026-03", sessions: 10 }], undatedSessions: 0, undatedReason: "no_timestamps", groups: [row()], ...over });

const taughtOf = (over) => ({
  on: "2026-03-05", month: "2026-03", lesson: "Unset the token first.", before: cell(3, 6), after: cell(0, 4), enough: false, ...over,
});
const natural = (over) => ({
  key: "n1", title: "gh fails on token", kind: "failure", first: "2026-03-01", last: "2026-03-02", sessionsWithGroup: 2,
  before: { times: 5, sessions: 3, per10: 16.7 }, after: { times: 0, sessions: 14, per10: 0 }, ...over,
});
const dayLabelEvil = trends({ groups: [row({ title: HOSTILE, trend: "gone", last: null })] });
const attr = (title) => {
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const decoded = esc(esc(title)).replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  return sandbox.window.SymbiontTip.safe(decoded);
};

const routing = require("./routing_probe.js")(sandbox, path);

console.log(JSON.stringify({
  routing,
  datasetNotReady: draw(T, notReady({ datasetReaders: ["swe-chat"] }), { compact: false }),
  ownNotReady: draw(T, notReady({ datasetReaders: [] }), { compact: false }),
  hostileTopic: draw(T, ready, { compact: true }),
  noDatesOld: draw(R, trends({ months: [], undatedSessions: 141, undatedReason: "old_store", groups: [] })),
  noDatesTruly: draw(R, trends({ months: [], undatedSessions: 141, groups: [] })),
  oldNote: draw(R, trends({ undatedSessions: 3, undatedReason: "old_store" })),
  trulyNote: draw(R, trends({ undatedSessions: 3, undatedReason: "no_timestamps" })),
  outside: draw(R, trends({ groups: [row({ outsideTimes: 4 })] })),
  goneNoLast: draw(R, dayLabelEvil),
  tooFew: draw(R, trends({ groups: [row({ trend: "too_few" })] })),
  replayTip: attr(HOSTILE),
  linked: draw(R, trends({ groups: [row({ key: "a&b c" })] })),
  lessons: draw(R, trends({ groups: [row({ taught: taughtOf() }), row({ key: "k2", title: "Other", taught: taughtOf({ lesson: HOSTILE, enough: true, after: cell(1, 12) }) })] })),
  lessonGone: draw(R, trends({ groups: [row({ title: "Group title", taught: taughtOf({ lesson: null }) })] })),
  noLessons: draw(R, trends()),
  found: draw(R, trends({ natural: natural() })),
  foundHostile: draw(R, trends({ natural: natural({ title: HOSTILE, key: "x\"y" }) })),
}));
