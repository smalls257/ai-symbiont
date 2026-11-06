// Loads the page's mining.js in a bare context and prints what describe() says for each state.
// Run by test_mining_view.py: `node mining_view_harness.js <path to mining.js>`.
const fs = require("fs");
const vm = require("vm");

const sandbox = { window: {}, document: {}, location: {} };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const describe = sandbox.window.SymbiontMining.describe;

const base = { sessions_read: 0, sessions_total: 40, pain_points: 0, fixes_paired: 0, lessons: 0, recent: [], error: null };
const continueUrl = sandbox.window.SymbiontMining.continueUrl;
const cases = {
  continueUrl: continueUrl("http://h:1/dashboard?project=a%20b&mining=1"),
  running: describe({ ...base, state: "running", sessions_read: 12, pain_points: 3, fixes_paired: 2, lessons: 4, recent: ["`pytest x` failed with ImportError"] }),
  done: describe({ ...base, state: "done", sessions_read: 40, pain_points: 5, fixes_paired: 4, lessons: 9 }),
  doneEmpty: describe({ ...base, state: "done", sessions_read: 40 }),
  doneStruggleOnly: describe({ ...base, state: "done", sessions_read: 40, pain_points: 5, session_facts: 40 }),
  failed: describe({ ...base, state: "failed", sessions_read: 7, error: "/logs/a.jsonl:3: not a JSON line" }),
  failedNoReason: describe({ ...base, state: "failed", sessions_read: 7 }),
};

// run() against a fake page: it must paint every state, show a lost connection and then reload.
function fakeElement() {
  const element = { style: { setProperty() {} }, dataset: {}, children: [], textContent: "", className: "" };
  element.classList = { add() {}, toggle() {} };
  element.appendChild = (child) => { element.children.push(child); return child; };
  element.append = (...kids) => { element.children.push(...kids); };
  element.replaceChildren = (...kids) => { element.children = kids; };
  element.setAttribute = () => {};
  return element;
}

async function drivenRun() {
  const page = {};
  const reply = (body, ok = true, status = 200) => ({ ok, status, json: async () => body });
  const answers = [
    () => { throw new Error("connection refused"); },
    () => reply({ ...base, state: "running", sessions_read: 20, pain_points: 2, recent: ["a", "b"] }),
    () => reply({ ...base, state: "done", sessions_read: 40, pain_points: 5, lessons: 9 }),
  ];
  const context = {
    window: {}, reloaded: false, timers: [],
    location: { href: "http://127.0.0.1:1/dashboard?project=my%20repo&mining=1", assign(url) { context.reloaded = url; } },
    document: {
      getElementById: (id) => (page[id] ||= fakeElement()),
      createElement: () => fakeElement(),
    },
    performance: { now: () => 0 }, requestAnimationFrame: (f) => f(1e6),
    setTimeout: (f, ms) => { if (ms >= 3000) context.timers.push([f, ms]); else f(); return 0; },
    fetch: async (url) => { context.urls.push(url); return answers.shift()(); }, urls: [],
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
  await context.window.SymbiontMining.run({ project: "my repo", progress: { ...base, state: "running", sessions_total: 40 } });
  const buttonBefore = { label: page.startBtn.textContent, shown: page.startBtn.style.display };
  const [autoMove, autoMs] = context.timers[0];
  const movedBefore = context.reloaded;
  page.startBtn.onclick();
  const byClick = context.reloaded;
  context.reloaded = false;
  autoMove();
  return {
    movedBefore, byClick, byTimer: context.reloaded, autoMs, buttonBefore, urls: context.urls, headline: page.h1.textContent,
    cells: page.sgrid.children.length, readCells: page.sgrid.children.filter((c) => c.className === "read").length,
    feed: page.feed.children.length, startHidden: page.startBtn.style.display, repo: page.repoName.textContent,
  };
}

drivenRun().then((driven) => {
  process.stdout.write(JSON.stringify({ ...cases, driven }));
});
