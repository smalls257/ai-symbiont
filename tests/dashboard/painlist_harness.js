// Loads the page's painlist.js in a bare context and prints what its storage and markup functions decide.
// Run by test_painlist.py: `node painlist_harness.js <path to painlist.js>`.
const fs = require("fs");
const vm = require("vm");

const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const L = sandbox.window.SymbiontPainList;

const memory = (initial) => {
  const data = { ...initial };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = v; },
  };
};
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const warnings = [];
const warn = (m) => warnings.push(m);
const key = "symbiont.plist.collapsed.demo";

const stored = memory({ [key]: '["repeat"]' });
const corrupt = memory({ [key]: "{not json" });
const wrongShape = memory({ [key]: '{"repeat":true}' });
const saved = memory({});
L.writeCollapsed(saved, "demo", new Set(["repeat", "tdd"]), warn);
const refusing = { getItem: () => null, setItem: () => { throw new Error("quota"); } };
L.writeCollapsed(refusing, "demo", new Set(["repeat"]), warn);

const groups = [
  { kind: "repeat", label: "Repeated failure", count: 14, itemsHtml: "<button>one</button>" },
  { kind: "tdd", label: "<b>x</b>", count: 0, itemsHtml: "" },
];
console.log(JSON.stringify({
  key: L.storageKey("demo"),
  missing: [...L.readCollapsed(memory({}), "demo", warn)],
  stored: [...L.readCollapsed(stored, "demo", warn)],
  otherProject: [...L.readCollapsed(stored, "other", warn)],
  corrupt: [...L.readCollapsed(corrupt, "demo", warn)],
  wrongShape: [...L.readCollapsed(wrongShape, "demo", warn)],
  saved: saved.data,
  warnings,
  openHtml: L.groupsHtml(groups, new Set(), esc),
  closedHtml: L.groupsHtml(groups, new Set(["repeat"]), esc),
}));
