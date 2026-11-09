// Drives routeFrom/hrefFor and views.mount with a fake page; returns plain values for test_views.py.
const HOSTILE_KEYS = ["failure:git add:fatal: pathspec <x> did not match", "correction:abc:12", 'say "hi" & go', "café #1?x=2"];

function roundTrips(M) {
  return HOSTILE_KEYS.map((key) => {
    const href = M.hrefFor("my proj", { view: "group", key, hash: "teach me" });
    const at = href.indexOf("#");
    return { href, back: M.routeFrom(href.slice(0, at), href.slice(at)) };
  });
}

function fakePage(sandbox) {
  const els = {};
  const el = (id) => (els[id] ||= { id, innerHTML: "", textContent: "", hidden: false, dataset: {}, style: {}, setAttribute() {}, querySelectorAll: () => [], insertAdjacentHTML() {} });
  const s1 = { dataset: {}, querySelector: (sel) => el(sel) };
  const handlers = {};
  const pushed = [];
  sandbox.location = { search: "?project=p&view=topics", hash: "", href: "http://127.0.0.1/dashboard?project=p&view=topics" };
  const setLocation = (url) => {
    const u = new URL(url, "http://127.0.0.1/dashboard");
    Object.assign(sandbox.location, { search: u.search, hash: u.hash, href: u.href });
  };
  sandbox.history = { pushState: (_s, _t, url) => { pushed.push(url); setLocation(url); }, replaceState: (_s, _t, url) => setLocation(String(url)) };
  sandbox.window.addEventListener = (name, fn) => { handlers[name] = fn; };
  sandbox.document.getElementById = el;
  sandbox.document.addEventListener = (name, fn) => { handlers[name] = fn; };
  sandbox.window.SymbiontInbox = { start() {}, refresh() { sandbox.refreshed = (sandbox.refreshed || 0) + 1; } };
  return { els, s1, handlers, pushed, setLocation };
}

module.exports = function probe(sandbox) {
  const M = sandbox.window.SymbiontInboxModel;
  const V = sandbox.window.SymbiontViews;
  const warnings = [];
  const warn = (m) => warnings.push(m);
  const unknown = M.routeFrom("?view=nope", "", warn);
  const steps = ["abc", "12", "1.5", "-3", ""].map((v) => M.routeFrom("?view=session&id=s1&step=" + v, "", warn).step ?? null);

  const { els, s1, handlers, pushed, setLocation } = fakePage(sandbox);
  const data = { stage: { facts: [1, 2, 3] }, incidents: { groups: [{ first: "2026-01-05", last: "2026-03-09" }, { first: "2026-02-01", last: "2026-04-02" }] } };
  const mounted = V.mount(data, "p", s1, warn);
  mounted.show();

  const calls = [];
  const render = (pane, route, d, project) => { calls.push({ route, project, same: d === data }); pane.innerHTML = "G:" + route.key; V.setCrumb("Group " + route.key); };
  const click = (href, extra) => {
    const e = { target: { closest: () => ({ href }) }, button: 0, prevented: false, preventDefault() { this.prevented = true; }, ...extra };
    handlers.click(e);
    return e.prevented;
  };

  V.navigate({ view: "session", id: "s1" });
  const unbuilt = els["#vSession"].innerHTML;
  const afterNavigate = { view: s1.dataset.view, url: pushed[0] };
  V.registerDetail("group", render);
  V.navigate({ view: "group", key: "a" });
  const crumbA = els.crumb.textContent;
  V.navigate({ view: "group", key: "b" });
  const plain = click("/dashboard?project=p&view=group&key=c%3Ad");
  const ctrl = click("/dashboard?project=p&view=group&key=zzz", { ctrlKey: true });
  const middle = click("/dashboard?project=p&view=group&key=zzz", { button: 1 });
  const pushedBeforePop = pushed.length;
  setLocation("?project=p&view=topics");
  handlers.popstate();
  const afterPop = { view: s1.dataset.view, crumb: els.crumb.textContent, crumbHidden: els.crumb.hidden };
  setLocation("?project=p&view=group");
  handlers.popstate();
  const visit = (search) => { setLocation(search); handlers.popstate(); };
  visit("?project=p&view=inbox"); visit("?project=p&view=topics");
  V.dataChanged(); visit("?project=p&view=inbox");
  const refreshedAfterChange = sandbox.refreshed || 0;
  visit("?project=p&view=topics"); visit("?project=p&view=inbox");
  const refreshedQuiet = sandbox.refreshed || 0;
  visit("?project=p&view=group");
  return {
    refreshedAfterChange, refreshedAfterQuietReturn: refreshedQuiet, roundTrip: roundTrips(M), hostile: HOSTILE_KEYS, unknown, steps, warnings, unbuilt, afterNavigate, crumbA, plain, ctrl, middle,
    pushedBeforePop, afterPop, calls, groupPane: els["#vGroup"].innerHTML, missing: els["#vNotFound"].innerHTML,
    notFoundView: s1.dataset.view, meta: els.meta.textContent, stage: mounted.stage,
  };
};
