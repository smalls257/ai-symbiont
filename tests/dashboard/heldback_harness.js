// Loads the page's heldback.js in a bare context and prints what its markup functions decide.
// Run by test_heldback.py: `node heldback_harness.js <path to heldback.js>`.
const fs = require("fs");
const vm = require("vm");

const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const H = sandbox.window.SymbiontHeldBack;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const entries = [
  { what: "`pytest <img src=x onerror=1>` fails with exit 1", reason: "no fix shown", sessions: 1, occurrences: 9, minutes: 18 },
  { what: "`make lint` fails", reason: "no fix shown", sessions: 4, occurrences: 1, minutes: 2 },
];
const group = H.group(entries, esc);
console.log(JSON.stringify({
  one: H.counted(1, "session"), many: H.counted(2, "session"), zero: H.counted(0, "time"),
  kind: group.kind, count: group.count, role: group.role, html: group.itemsHtml,
}));
