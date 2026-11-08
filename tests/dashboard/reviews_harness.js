// Runs "What reviewers flagged" (inbox_reviews.js) with the real model, rows and shared triage actions on a tiny fake DOM,
// and prints plain values. Run by test_inbox_reviews.py: `node reviews_harness.js <static dir>`
const fs = require("fs");
const vm = require("vm");
const path = require("path");

class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.className = ""; this.parent = null; this._text = ""; this.id = ""; this.open = false; this.hidden = false; this.handler = null; }
  get dataset() { const out = {}; for (const [k, v] of Object.entries(this.attributes)) if (k.startsWith("data-")) out[k.slice(5)] = v; return out; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  replaceChildren(...kids) { this.children = []; kids.forEach((k) => this.appendChild(k)); }
  addEventListener(type, fn) { if (type === "click") this.handler = fn; }
  closest(sel) {
    const attr = /^\[([\w-]+)\]$/.exec(sel);
    for (let n = this; n; n = n.parent) if (attr ? attr[1] in n.attributes : false) return n;
    return null;
  }
  all(test, out = []) { if (test(this)) out.push(this); this.children.forEach((c) => c.all(test, out)); return out; }
}
const textNode = (text) => { const n = new Node("#text"); n._text = text; return n; };
const document = { createElement: (tag) => new Node(tag), createTextNode: textNode };

const posts = [];
const toasts = [];
const sandbox = { window: {}, document, URLSearchParams, console };
sandbox.fetch = async (url, init) => {
  posts.push([url, JSON.parse(init.body)]);
  return { ok: true, status: 200, text: async () => JSON.stringify({ state: "archived", taught_on: null }) };
};
sandbox.window.SymbiontInboxDialogs = { toast: (container, message) => toasts.push(message) };
for (const file of ["inbox_model.js", "inbox_rows.js", "triage_actions.js", "inbox_reviews.js"]) {
  vm.runInNewContext(fs.readFileSync(path.join(process.argv[2], file), "utf8"), sandbox);
}
const Reviews = sandbox.window.SymbiontInboxReviews;

const HOSTILE = "<img src=x onerror=window.__x=1>";
const example = (over) => ({ gist: "Possible null dereference", file: "src/a.ts", sessionId: "s1", step: 3, date: "2026-03-09", ...over });
const group = (key, over) => ({
  key, gist: "Possible null dereference", count: 3, sessions: 2, reviewers: ["CodeRabbit", "Copilot"], files: ["src/a.ts"],
  fixedBy: ["a.ts"], examples: [example()], lessonIds: ["s1:3:review_flag"], last: "2026-03-09", ...over,
});
const single = (i) => group("review:single" + i, { count: 1, sessions: 1, gist: "Single " + i, reviewers: ["a teammate"], examples: [example({ gist: "Single " + i, step: i })] });

function fixture(reviews, triage = {}, open = []) {
  const section = new Node("section");
  const focused = [];
  const container = { querySelector: () => null };
  const ui = { container, project: "my repo", data: { reviews, triage }, open: new Set(open), $: () => section };
  Reviews.mount(ui);
  const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
  const find = (test) => section.all(test);
  const click = async (button) => {
    section.handler({ target: { closest: (sel) => (sel === "button[data-v]" ? button : null) } });
    await settle();
  };
  const rows = () => find((n) => n.className === "rrow vrow");
  const buttons = (word) => find((n) => n.tagName === "button" && n.textContent === word);
  return { ui, section, find, click, rows, buttons, redraw: () => Reviews.draw(ui) };
}

(async () => {
  const mixed = [group("review:a", { gist: HOSTILE, examples: [example({ gist: HOSTILE })] }), group("review:b", { count: 2, sessions: 2 }),
    ...Array.from({ length: 20 }, (_, i) => single(i))];
  const closed = fixture({ groups: mixed, dismissed: 2 });
  const afterClosed = {
    hidden: closed.section.hidden, title: closed.find((n) => n.tagName === "h2")[0].textContent,
    rowTexts: closed.rows().map((r) => r.textContent), links: closed.find((n) => n.tagName === "a").map((a) => [a.attributes.href, a.attributes["data-route"]]),
    summary: closed.find((n) => n.tagName === "summary")[0].textContent, foldOpen: closed.find((n) => n.tagName === "details")[0].open,
    tags: closed.find(() => true).map((n) => n.tagName).filter((t) => t === "img"),
    hostileRowLabel: closed.rows()[0].attributes["aria-label"],
  };
  const opened = fixture({ groups: mixed }, {}, ["inReviewsOnce"]);
  const firstPage = { rows: opened.rows().length, more: opened.buttons("Show 5 more comments").length };
  await opened.click(opened.buttons("Show 5 more comments")[0]);
  const secondPage = { rows: opened.rows().length, more: opened.find((n) => n.className === "btn more").length };

  const one = fixture({ groups: [group("review:a"), group("review:b", { count: 2 })] });
  await one.click(one.buttons("Dismiss")[0]);
  const dismissed = { posts: posts.splice(0), rows: one.rows().map((r) => r.attributes["data-review"]), toasts: toasts.splice(0),
    title: one.find((n) => n.tagName === "h2")[0].textContent, triage: one.ui.data.triage };
  const onlyOne = fixture({ groups: [group("review:a")] });
  await onlyOne.click(onlyOne.buttons("Dismiss")[0]);
  const emptied = { hidden: onlyOne.section.hidden, children: onlyOne.section.children.length };

  const preDismissed = fixture({ groups: [group("review:a")] }, { "review:a": { state: "archived" } });
  const none = fixture({ groups: [], dismissed: 0 });
  const missing = fixture(undefined);
  const single1 = fixture({ groups: [single(1)] });
  console.log(JSON.stringify({
    afterClosed, firstPage, secondPage, dismissed, emptied,
    preDismissed: [preDismissed.section.hidden, preDismissed.section.children.length],
    none: [none.section.hidden, none.section.children.length], missing: [missing.section.hidden, missing.section.children.length],
    onlySingles: { fold: single1.find((n) => n.tagName === "summary")[0].textContent, rows: single1.rows().length },
  }));
})();
