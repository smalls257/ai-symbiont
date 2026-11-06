// Loads the page's timeline.js in a bare context and prints what its layout functions decide.
// Run by test_timeline.py: `node timeline_harness.js <path to timeline.js>`.
const fs = require("fs");
const vm = require("vm");

const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const T = sandbox.window.SymbiontTimeline;

const point = (title, s) => ({ title, kind: "repeat", s, turns: 4 });
const many = Array.from({ length: 8 }, (_, i) => point("m" + i, Array.from({ length: 9 - i }, (_, k) => k * 3 + i % 2)));
many.push(point("only once", [5]));
console.log(JSON.stringify({
  rows: T.foldRows(many),
  fewRows: T.foldRows(many.slice(0, 3)).map((r) => r.title),
  short: T.labelLines("your edits to `ledger/refunds.py` were redone", 40),
  long: T.labelLines("your edits to `ledger/refunds.py` were redone again and again after every single review", 40),
  path: T.labelLines("x".repeat(100), 40),
  empty: T.labelLines("", 40),
  ticks: [T.tickStep(60, 1280), T.tickStep(5, 1280), T.tickStep(1, 1280)],
  radii: [T.dotRadius(60, 1280), T.dotRadius(5, 1280), T.dotRadius(1, 1280)],
}));
