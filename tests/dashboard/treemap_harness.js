// Loads the page's treemap.js in a bare context and prints what its layout functions decide.
// Run by test_treemap.py: `node treemap_harness.js <path to treemap.js>`.
const fs = require("fs");
const vm = require("vm");

const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const T = sandbox.window.SymbiontTreemap;

const shaped = [
  ["", 36], ["ledger/statements.py", 10], ["ledger/test_balance_after_a_very_long_name.py", 8], ["ledger/summary.py", 8],
  ["ledger/refunds.py", 8], ["ledger/ledger.py", 6], ["a.py", 2], ["b.py", 2], ["c.py", 1], ["d.py", 1], ["e.py", 1], ["f.py", 1],
].map(([f, v]) => ({ f, v }));
console.log(JSON.stringify({
  tiles: T.plan(shaped, 478, 245),
  roomy: T.plan(shaped.slice(0, 3), 900, 500),
  single: T.plan([{ f: "only.py", v: 5 }], 478, 245),
  none: T.plan([], 478, 245),
  names: [T.fileName("ledger/refunds.py"), T.fileName(""), T.fileName(undefined), T.fileName("dir/")],
  fit: [T.fitName("statements.py", 100, 13), T.fitName("a.py", 130, 13), T.fitName("x".repeat(60), 90, 13)],
  font: [T.fitFont("Other files (7)", 110, 13), T.fitFont("Other files (7)", 400, 13), T.fitFont("Other files (700)", 60, 13)],
  min: [T.MIN_W, T.MIN_H],
  loose: [
    T.noFileLabel([{ file: "", command: "pytest" }, { file: "a.py", command: null }]),
    T.noFileLabel([{ file: "", command: "pytest" }, { file: "", command: null }]),
    T.noFileLabel([{ file: "a.py", command: null }]),
  ],
  labeled: T.plan([{ f: "", v: 9, label: T.FAILED_COMMANDS }, { f: "a.py", v: 3 }], 478, 245).map(t => t.name),
}));
