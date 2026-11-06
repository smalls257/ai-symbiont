// Loads ignored.js in a bare context and prints what its storage and markup functions decide.
// Run by test_ignored_list.py: `node ignored_harness.js <path to ignored.js>`.
const fs = require("fs");
const vm = require("vm");

const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const I = sandbox.window.SymbiontIgnored;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const memory = (data) => ({ getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = v; } });
const warnings = [];
const broken = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("quota"); } };

const saved = memory({});
I.writeOpen(saved, "demo", true, (m) => warnings.push(m));
const entry = { label: '<img src=x onerror="1"> & more', signal: "failed_command", key: ["pytest"] };
console.log(JSON.stringify({
  key: I.storageKey("demo"),
  defaultOpen: I.readOpen(memory({}), "demo", () => {}),
  afterOpening: I.readOpen(saved, "demo", () => {}),
  brokenOpen: I.readOpen(broken, "demo", (m) => warnings.push(m)),
  html: I.itemsHtml([entry], esc),
  empty: I.itemsHtml([], esc),
  group: I.group([entry], esc),
  warnings,
}));
