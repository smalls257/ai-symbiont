// Runs "Rules you've stated" (inbox_rules.js) with the real model, rows and shared triage actions, and prints plain values.
// Run by test_inbox_rules.py: `node rules_harness.js <static dir>`
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const HOSTILE = "<img src=x onerror=window.__x=1>";
const posts = [];
const toasts = [];
const sandbox = { window: {}, URLSearchParams, console };
sandbox.fetch = async (url, init) => {
  const body = JSON.parse(init.body);
  posts.push([url, body]);
  const answer = url === "/lessons/add" ? { ids: ["L1"] } : { state: body.state || "for_review", taught_on: body.taught ? "2026-11-07" : null };
  return { ok: true, status: 200, text: async () => JSON.stringify(answer) };
};
const drafts = [];
sandbox.window.SymbiontInboxDialogs = {
  toast: (container, message) => toasts.push(message),
  // Stands in for the dialog: opens with the draft the real one is given, saves it unchanged.
  teach: (ui, g, button, done) => {
    const M = sandbox.window.SymbiontInboxModel;
    const draft = M.teachDraft(g, M.displayName(ui.data.triage, g), true);
    drafts.push(draft);
    return done(ui, g, M.lessonRequest(ui.project, g, draft.when, draft.what, draft.name));
  },
};
for (const file of ["inbox_model.js", "inbox_rows.js", "triage_actions.js", "inbox_rules.js"]) {
  vm.runInNewContext(fs.readFileSync(path.join(process.argv[2], file), "utf8"), sandbox);
}
const W = sandbox.window;
const Rules = W.SymbiontInboxRules;

const item = (key, over) => ({
  key, text: "Use pnpm, not npm.", confirmed: true, scope: "repo", area: "", times: 4, sessions: 3,
  first: "2026-01-01", last: "2026-03-09", state: "new",
  examples: [{ text: "always use pnpm", sessionId: "s2", step: 3, date: "2026-03-09" }], ...over,
});
const items = (n) => Array.from({ length: n }, (_, i) => item("rule:s" + i + ":1", { text: "Rule " + i }));

function fixture(rules, triage = {}) {
  const holder = { innerHTML: "" };
  let handler = null;
  holder.addEventListener = (type, fn) => { if (type === "click") handler = fn; };
  const container = { querySelector: (sel) => (sel === "#inRules" ? holder : null) };
  const ui = { container, project: "my repo", data: { rules, triage }, $: (sel) => (sel === "#inRules" ? holder : null) };
  Rules.mount(ui);
  const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
  const click = async (rule, kind) => { handler({ target: { closest: (sel) => (sel === "button[data-r]" ? {
    dataset: { r: kind }, closest: () => ({ dataset: { rule } }) } : null) } }); await settle(); };
  return { ui, holder, click };
}

(async () => {
  const one = fixture({ confirmed: true, items: [item("rule:s2:3")] });
  const guess = fixture({ confirmed: false, items: [item("rule:g:1", { confirmed: false, text: "use pnpm" })] });
  const area = fixture({ confirmed: true, items: [item("rule:a:1", { scope: "area", area: "web/" })] });
  const hostile = fixture({ confirmed: true, items: [item("rule:h:1", {
    text: HOSTILE, area: HOSTILE, scope: "area", examples: [{ text: HOSTILE, sessionId: HOSTILE, step: 1, date: null }] })] });
  const empty = fixture({ confirmed: false, items: [] });
  const missing = fixture(undefined);
  const seven = fixture({ confirmed: true, items: items(7) });
  const initial = { html: one.holder.innerHTML, guess: guess.holder.innerHTML };
  const foldedRows = (seven.holder.innerHTML.match(/class="rrow"/g) || []).length;
  const foldedButton = /Show 2 more rules/.test(seven.holder.innerHTML);
  await seven.click("rule:s0:1", "more");
  const openRows = (seven.holder.innerHTML.match(/class="rrow"/g) || []).length;

  await one.click("rule:s2:3", "teach");
  const afterTeach = one.holder.innerHTML;
  await area.click("rule:a:1", "teach");
  const teachPosts = posts.splice(0, 2);
  posts.splice(0);
  await guess.click("rule:g:1", "dismiss");
  const dismissPosts = posts.splice(0);

  console.log(JSON.stringify({
    html: initial.html, guess: initial.guess, hostile: hostile.holder.innerHTML,
    empty: empty.holder.innerHTML, missing: missing.holder.innerHTML,
    foldedRows, foldedButton, openRows, drafts, teachPosts, dismissPosts, afterTeach, toasts,
    afterDismiss: guess.holder.innerHTML, triage: guess.ui.data.triage,
    examples: Rules.sectionHtml({ items: [item("k")] }, "my repo", {}, false),
  }));
})();
