(function () {
"use strict";
/* The Pain points stage: one selection (a theme, a pattern, or both) scopes every panel.
   Sessions are summarized at mining time; this file only counts and draws them, so a click is instant.
   Every value that came from a record goes in through esc() or textContent. */
const DATA = window.SYMBIONT_DATA || JSON.parse(document.getElementById("symbiont-data").textContent);
if (DATA.mining) return;
const S = DATA.stage;
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fmt = n => Math.round(n).toLocaleString("en-US");
const pct = (a, b) => b ? Math.round(100 * a / b) : 0;
const HB = window.SymbiontHeldBack, PL = window.SymbiontPainList, HEAT = window.SymbiontHeat;
const CODE_FIX = "code_fix", CORRECTED = "corrected_command";

if (!S) {
  $("s1").classList.add("bare");
  $("kpis").innerHTML = '<div class="panel kpi none">This repository was mined before sessions were summarized. Run <span class="mono">symbiont repo mine</span> again to see themes, patterns and a session here.</div>';
  return;
}

const MINUTES_PER_TURN = S.minutesPerTurn;
const F = S.facts, ALL = F.map((_, i) => i);
const PAT = Object.fromEntries(S.patterns.map(p => [p.id, p]));
const PIDS = S.patterns.map(p => p.id);
const sel = {theme: null, pattern: null};
let tab = "themes", cursor = 0, drawn = null;
const inScope = i => (!sel.theme || F[i].themes.includes(sel.theme)) && (!sel.pattern || F[i].patterns.includes(sel.pattern));

/* A control that is clicked is also reached by keyboard: Enter or Space does the same. */
function press(el, fn) {
  el.onclick = fn;
  el.setAttribute("tabindex", "0"); el.setAttribute("role", "button");
  el.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } };
}
/* A tip is plain lines: the first in bold on hover, all of them as the accessible name. */
function tipAttrs(lines) {
  return ' data-tip="<b>' + esc(esc(lines[0])) + "</b>" + lines.slice(1).map(l => "<br>" + esc(esc(l))).join("") + '" aria-label="' + esc(lines.join(", ")) + '"';
}

function stats(idxs) {
  const o = {fixed: 0, corrected: 0, failures: 0}, pats = Object.fromEntries(PIDS.map(p => [p, 0]));
  let turns = 0, struggled = 0;
  idxs.forEach(i => {
    const f = F[i]; turns += f.turns; if (f.struggled) struggled++;
    Object.entries(f.outcomes).forEach(([k, v]) => { o.failures += v; if (k === CODE_FIX) o.fixed += v; if (k === CORRECTED) o.corrected += v; });
    f.patterns.forEach(p => pats[p]++);
  });
  return {n: idxs.length, turns, struggled, fixed: o.fixed, corrected: o.corrected, failures: o.failures, pats};
}
const ALLS = stats(ALL);

/* Themes, ranked once for the whole history: the struggle rates furthest from the average first. */
const THEMES = (() => {
  const base = ALLS.struggled / ALLS.n;
  const rows = S.themeWords.map(w => { const s = stats(ALL.filter(i => F[i].themes.includes(w))); return {w, s, rate: s.struggled / s.n}; })
    .filter(r => r.s.n >= S.minThemeSessions);
  return rows.sort((a, b) => Math.abs(b.rate - base) - Math.abs(a.rate - base)).slice(0, 16).sort((a, b) => b.rate - a.rate);
})();

function setSel(theme, pattern) { sel.theme = theme; sel.pattern = pattern; cursor = 0; render(); }
const toggle = (kind, v) => setSel(kind === "theme" ? (sel.theme === v ? null : v) : sel.theme, kind === "pattern" ? (sel.pattern === v ? null : v) : sel.pattern);
const toggleCell = (t, p) => (sel.theme === t && sel.pattern === p) ? setSel(null, null) : setSel(t, p);

function renderScope(scoped) {
  const chips = [];
  if (sel.theme) chips.push(["theme", sel.theme]);
  if (sel.pattern) chips.push(["pattern", PAT[sel.pattern].short]);
  $("scope").innerHTML = chips.length
    ? "Scope " + chips.map(c => '<span class="chip">' + esc(c[1]) + '<button data-clear="' + c[0] + '" aria-label="Clear ' + esc(c[1]) + '">✕</button></span>').join("") + "<span>" + HB.counted(scoped.n, "session") + "</span>"
    : "<span>All " + HB.counted(ALLS.n, "session") + " · click a theme, pattern or cell to scope</span>";
  $("scope").title = $("scope").textContent.replace(/✕/g, "").trim();
  $("scope").querySelectorAll("[data-clear]").forEach(b => b.onclick = () => b.dataset.clear === "theme" ? setSel(null, sel.pattern) : setSel(sel.theme, null));
}

function renderKpis(s, lessons) {
  const scoped = sel.theme || sel.pattern;
  const against = (all, unit) => '<span class="of">of ' + all + unit + " across all sessions</span>";
  const hrs = s.turns * MINUTES_PER_TURN / 60, allHrs = ALLS.turns * MINUTES_PER_TURN / 60;
  $("kpis").innerHTML = [
    [fmt(s.turns), "agent turns lost", scoped ? against(fmt(ALLS.turns), "") : '<span class="of">from a failure to the next pass of the same program</span>', "var(--rd)"],
    ["~" + fmt(hrs) + " h", "of working time lost, estimated", scoped ? against("~" + fmt(allHrs), " h") : '<span class="of">a hypothesis: ' + MINUTES_PER_TURN + " min per turn, not measured</span>", "var(--or)"],
    [fmt(lessons.length), "lessons ready", scoped ? against(fmt(S.lessons.length), "") : '<span class="of">a known fix, seen in at least ' + HB.counted(S.minSessions, "session") + "</span>", "var(--vi)"],
    [pct(s.fixed + s.corrected, s.failures) + "%", "of failures ended in a known fix", '<span class="of">' + fmt(s.fixed) + " code edits, " + fmt(s.corrected) + " corrected commands" + (scoped ? " (all: " + pct(ALLS.fixed + ALLS.corrected, ALLS.failures) + "%)" : "") + "</span>", "var(--gr)"],
  ].map(k => '<div class="panel kpi"><div class="num" style="color:' + k[3] + '">' + k[0] + '</div><div class="lbl">' + k[1] + k[2] + "</div></div>").join("");
}

const shareHtml = (count, n) => { const l = HEAT.shareLabel(count, n); return l.endsWith("%") ? l.slice(0, -1) + "<small>%</small>" : l; };
function renderPatterns(s) {
  const rows = PIDS.map(p => ({p, count: s.pats[p], share: s.pats[p] / Math.max(1, s.n), all: ALLS.pats[p] / ALLS.n, allCount: ALLS.pats[p]})).sort((a, b) => b.share - a.share);
  const mx = Math.max(...rows.map(r => Math.max(r.share, r.all)), 0.01);
  $("pats").innerHTML = rows.map(r => {
    const P = PAT[r.p], lines = [P.name, P.means].concat(sel.theme ? ["all sessions: " + HEAT.shareLabel(r.allCount, ALLS.n)] : []);
    return '<div class="ptn' + (P.teachable ? "" : " quiet") + (sel.pattern === r.p ? " sel" : "") + '" data-p="' + r.p + '" aria-pressed="' + (sel.pattern === r.p) + '"' + tipAttrs(lines) + ">"
      + '<div class="nm">' + esc(P.name) + '</div><div class="v">' + shareHtml(r.count, s.n) + "</div>"
      + '<div class="tr"><i style="width:' + (100 * r.share / mx) + '%"></i>' + (sel.theme ? '<b style="left:' + (100 * r.all / mx) + '%"></b>' : "") + "</div>"
      + '<div class="act">→ <em>' + esc(P.help) + "</em></div></div>";
  }).join("");
  $("pats").querySelectorAll(".ptn").forEach(d => press(d, () => toggle("pattern", d.dataset.p)));
}

/* The midpoint color under faint hatching: a cell with nothing honest to compare says so rather than looking "usual". */
const NO_COMPARISON = "repeating-linear-gradient(135deg, rgba(236,240,248,.14) 0 2px, transparent 2px 6px), #3a3550";
function divergingColor(r) {
  if (r >= 1.8) return "#ff8c40"; if (r >= 1.35) return "#b96a3e"; if (r >= 1.12) return "#6e4f4a";
  if (r <= 0.55) return "#3f86b8"; if (r <= 0.75) return "#35617f"; if (r <= 0.9) return "#33475a"; return "#3a3550";
}
function themeCell(r, p) {
  const v = r.s.pats[p] / r.s.n, all = ALLS.pats[p] / ALLS.n;
  const cmp = HEAT.compareCell({theme: r.w, themeSessions: r.s.n, themePattern: r.s.pats[p], allSessions: ALLS.n, allPattern: ALLS.pats[p]});
  const ratio = cmp.ratio;
  const on = sel.theme === r.w, isSel = on && sel.pattern === p, dim = (sel.theme && !on) || (sel.pattern && sel.pattern !== p);
  const lines = [HEAT.shareLabel(r.s.pats[p], r.s.n) + " of " + r.w + " sessions", PAT[p].short + " (usual: " + HEAT.shareLabel(ALLS.pats[p], ALLS.n) + ")", cmp.compared ? (ratio >= 1 ? ratio.toFixed(1) + "× the usual rate" : "less common than usual") : cmp.reason];
  return '<div class="c' + (isSel ? " sel" : "") + (dim && !isSel ? " dim" : "") + '" data-t="' + esc(r.w) + '" data-p="' + p + '" style="background:' + (cmp.compared ? divergingColor(ratio) : NO_COMPARISON) + '"' + tipAttrs(lines) + "></div>";
}
function renderThemes() {
  $("mapTitle").textContent = "What was being worked on";
  const base = ALLS.struggled / ALLS.n;
  $("mapSub").textContent = THEMES.length
    ? "Themes from the tasks, in the codebase's own words: struggle rate against the " + Math.round(base * 100) + "% average, then which patterns are unusually common. Click a theme, a column or a cell."
    : "No theme is shared by enough sessions yet. Themes appear once the same codebase word turns up in several tasks.";
  let h = '<div class="ch"></div><div class="ch">struggle<br>vs average</div>' + PIDS.map(p => '<div class="ch p' + (sel.pattern === p ? " sel" : "") + '" data-p="' + p + '">' + esc(PAT[p].short).replace(" ", "<br>") + "</div>").join("");
  THEMES.forEach(r => {
    const d = r.rate - base, w = Math.min(100, Math.abs(d) / 0.2 * 100), on = sel.theme === r.w, eg = (S.titles[r.w] || [""])[0];
    h += '<div class="rl' + (on ? " sel" : "") + '" data-t="' + esc(r.w) + '"' + tipAttrs([r.w, HB.counted(r.s.n, "session"), "e.g. " + eg]) + ">" + esc(r.w) + "<small>" + fmt(r.s.n) + "</small></div>";
    h += '<div class="rate" data-t="' + esc(r.w) + '"' + tipAttrs([Math.round(r.rate * 100) + "% of " + r.w + " sessions struggled (average " + Math.round(base * 100) + "%)"]) + '><i class="' + (d >= 0 ? "up" : "dn") + '" style="width:' + w + '%"></i></div>';
    h += PIDS.map(p => themeCell(r, p)).join("");
  });
  $("hm").style.gridTemplateColumns = "minmax(10.5rem,1.4fr) 6rem repeat(" + PIDS.length + ",1fr)";
  $("hm").innerHTML = h;
  $("hm").querySelectorAll(".rl[data-t],.rate[data-t]").forEach(e => press(e, () => toggle("theme", e.dataset.t)));
  $("hm").querySelectorAll(".ch.p").forEach(e => press(e, () => toggle("pattern", e.dataset.p)));
  $("hm").querySelectorAll(".c[data-t]").forEach(e => press(e, () => toggleCell(e.dataset.t, e.dataset.p)));
  const sw = c => '<span style="background:' + c + '"></span>';
  $("hmLegend").innerHTML = "<span>Pattern, compared with all sessions:</span><span>less" + '<span class="ramp">' + ["#3f86b8", "#35617f", "#33475a", "#3a3550", "#6e4f4a", "#b96a3e", "#ff8c40"].map(sw).join("") + '</span>more</span><span><span class="ramp"><span style="background:' + NO_COMPARISON + '"></span></span>too rare to compare</span><span><span class="dot" style="background:var(--rd)"></span>struggles more than average</span><span><span class="dot" style="background:var(--cy)"></span>less</span>';
}

/* Files: of the sessions in scope, the share of each month's that edited the file. */
const ramp = v => v === 0 ? "rgba(236,240,248,.05)" : ["#4a3470", "#7a4a6a", "#a95c5a", "#d9734a", "#ff8c40"][[0.05, 0.12, 0.2, 0.35].filter(c => v >= c).length];
function fileRows(scope) {
  const perMonth = S.months.map(() => 0);
  scope.forEach(i => { if (S.monthOf[i] !== null) perMonth[S.monthOf[i]]++; });
  const rows = S.files.map(f => {
    const mine = f.sessions.filter(i => scope.has(i)), cells = S.months.map(() => 0);
    mine.forEach(i => { if (S.monthOf[i] !== null) cells[S.monthOf[i]]++; });
    return {file: f.file, n: mine.length, cells: cells.map((c, m) => ({c, share: perMonth[m] ? c / perMonth[m] : 0}))};
  }).filter(r => r.n > 0);
  return rows.sort((a, b) => b.n - a.n);
}
function renderFiles(scope) {
  $("mapTitle").textContent = "Where in the repo, month by month";
  const scoped = sel.theme || sel.pattern, rows = fileRows(scope), M = S.months, every = Math.ceil(M.length / 12);
  $("mapSub").textContent = "Share of each month's " + (scoped ? "scoped " : "") + "sessions that edited the file (the most edited files overall).";
  let h = '<div class="ch"></div>' + M.map((m, i) => '<div class="ch">' + (i % every === 0 ? esc(m.slice(2)) : "") + "</div>").join("") + '<div class="ch">sessions</div>';
  rows.forEach(r => {
    h += '<div class="rl mono" title="' + esc(r.file) + '">' + esc(r.file) + "</div>";
    r.cells.forEach((c, i) => { h += '<div class="c" tabindex="0" style="background:' + ramp(c.share) + '"' + tipAttrs([c.c ? Math.round(c.share * 100) + "% of sessions" : "no edits", r.file + ", " + M[i]]) + "></div>"; });
    h += '<div class="rl" style="text-align:right">' + r.n + "</div>";
  });
  $("hm").style.gridTemplateColumns = "minmax(12rem,1.3fr) repeat(" + M.length + ",1fr) 3.2rem";
  $("hm").innerHTML = rows.length ? h : '<div class="empty">No frequently edited file in this scope.</div>';
  $("hmLegend").innerHTML = "<span>A band that never cools is a hard area; one hot cell is a one-off.</span>";
}
function setTab(name) {
  tab = name;
  $("tThemes").setAttribute("aria-pressed", name === "themes"); $("tFiles").setAttribute("aria-pressed", name === "files");
  render();
}
$("tThemes").onclick = () => setTab("themes");
$("tFiles").onclick = () => setTab("files");

function scopedLessons(scope) {
  return S.lessons.map(l => ({l, n: l.sessions.filter(i => scope.has(i)).length})).filter(x => x.n > 0).sort((a, b) => b.n - a.n);
}
function renderLessons(list) {
  const scoped = sel.theme || sel.pattern;
  $("lesSub").textContent = scoped ? "Lessons whose trouble shows up in this scope, most sessions first" : "A known fix (a code edit or a corrected command) that came back in at least " + HB.counted(S.minSessions, "session");
  $("les").innerHTML = list.length ? list.slice(0, 8).map(({l, n}) => '<li><button data-id="' + esc(l.id) + '"' + tipAttrs([l.title, HB.counted(l.occurrences, "time") + " in " + HB.counted(l.sessions.length, "session") + " overall", "click to add your own context"]) + '><span class="t">' + esc(l.title) + '</span><span class="big">' + n + "<small>" + (scoped ? "of " + HB.counted(l.sessions.length, "session") : (n === 1 ? "session" : "sessions")) + "</small></span>" + (l.fix ? '<span class="why">' + esc(l.fix) + "</span>" : "") + "</button></li>").join("")
    : '<li class="empty">No lesson-grade trouble in this scope: the struggle here never ended in a known fix.</li>';
  $("les").querySelectorAll("button").forEach(b => b.onclick = () => document.dispatchEvent(new CustomEvent("symbiont:open-lesson", {detail: {lessonId: b.dataset.id}})));
  renderHeld();
}
/* The failures mining counted but would not teach (no fix shown). They are counted over all sessions, so a selection does not narrow them. */
let heldOpen = false;
function renderHeld() {
  const groups = DATA.struggle || [];
  $("held").textContent = S.heldBack ? "Overall, " + S.heldBack + "." : "";
  $("heldSub").textContent = groups.length ? "These failures are listed across all sessions: your selection does not narrow them." : "";
  $("heldList").innerHTML = groups.length ? PL.groupsHtml([HB.group(groups, esc)], heldOpen ? new Set() : new Set([HB.KIND]), esc) : "";
  const toggleHeld = $("heldList").querySelector("button.grp");
  if (toggleHeld) toggleHeld.onclick = () => { heldOpen = !heldOpen; renderHeld(); $("heldList").querySelector("button.grp").focus(); };
}

/* One session, step by step: the densest struggle in scope, with a cursor for the arrow keys. */
/* Passed commands are most of any session and say nothing about the struggle; only failures are drawn. */
const LANE_Y = {you: 0.2, edit: 0.5, scratch: 0.5, failed: 0.8};
const LANE_WORDS = {you: "you wrote", edit: "edit in the codebase", scratch: "edit to a scratch file", failed: "command failed"};
const LANE_COLOR = {you: "#5cc8ff", edit: "#ff8c40", failed: "#f45454"};
const drawnSteps = st => st.steps.filter(s => s[1] in LANE_Y);
function stepMark(s, x, y, at) {
  const [step, lane, label] = s, ring = at ? ' stroke="#ecf0f8" stroke-width="3"' : ' stroke="#16112a" stroke-width="2"';
  const tip = ' data-tip="' + esc(esc(label)) + "<br>" + LANE_WORDS[lane] + ', step ' + step + '"';
  if (lane === "scratch") return '<circle cx="' + x + '" cy="' + y + '" r="5" fill="none" stroke="' + (at ? "#ecf0f8" : "#8c94ac") + '" stroke-width="2"' + tip + "/>";
  return '<circle cx="' + x + '" cy="' + y + '" r="' + 6 + '" fill="' + LANE_COLOR[lane] + '"' + ring + tip + "/>";
}
function renderStrip(scope) {
  const svg = $("stripsvg"), found = Object.entries(S.strips).filter(([i]) => scope.has(+i)).sort((a, b) => b[1].burst - a[1].burst)[0];
  if (!found) { drawn = null; $("stripSub").textContent = "No example session drawn for this scope."; svg.innerHTML = ""; $("stripNow").textContent = ""; return; }
  const st = found[1], steps = drawnSteps(st);
  if (drawn !== st) { drawn = st; cursor = 0; }
  const first = steps[0][0], last = Math.max(first + 1, steps[steps.length - 1][0]);
  $("stripSub").textContent = (sel.theme || sel.pattern ? "The densest struggle in this scope" : "The densest struggle overall") + " (" + st.task + "), " + (st.total > st.steps.length ? "steps " + fmt(st.offset + 1) + "–" + fmt(st.offset + st.steps.length) + " of " + fmt(st.total) + ", around the worst burst" : st.steps.length + " steps") + ". Shaded: " + S.burstFailures + " or more failures within " + S.burstSteps + " steps.";
  const b = svg.getBoundingClientRect(), W = Math.round(b.width) || 1600, H = Math.round(b.height) || 200, X0 = 150, X1 = W - 20;
  const xs = n => X0 + ((n - first) / (last - first)) * (X1 - X0), ys = lane => H * LANE_Y[lane];
  let h = st.bursts.map(([a, z]) => '<rect x="' + (xs(a) - 8) + '" y="4" width="' + (xs(z) - xs(a) + 16) + '" height="' + (H - 26) + '" rx="8" fill="rgba(244,84,84,.12)"/>').join("");
  [["you", "you"], ["edits", "edit"], ["commands", "failed"]].forEach(([name, lane]) => { h += '<text x="' + (X0 - 16) + '" y="' + (ys(lane) + 5) + '" text-anchor="end" font-size="15" fill="#8c94ac">' + name + '</text><line x1="' + X0 + '" x2="' + X1 + '" y1="' + ys(lane) + '" y2="' + ys(lane) + '" stroke="rgba(236,240,248,.1)" stroke-width="2"/>'; });
  h += steps.map((s, k) => stepMark(s, xs(s[0]), ys(s[1]), k === cursor)).join("");
  [["failed", "#f45454"], ["edit in codebase", "#ff8c40"], ["you", "#5cc8ff"]].forEach((l, i) => { h += '<circle cx="' + (X0 + i * 150) + '" cy="' + (H - 6) + '" r="5" fill="' + l[1] + '"/><text x="' + (X0 + i * 150 + 10) + '" y="' + (H - 1) + '" font-size="13" fill="#8c94ac">' + l[0] + "</text>"; });
  svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.innerHTML = h;
  const here = steps[cursor];
  $("stripNow").textContent = "Step " + here[0] + " (" + (cursor + 1) + " of " + steps.length + "): " + LANE_WORDS[here[1]] + ", " + here[2];
}
$("stripsvg").addEventListener("keydown", e => {
  if (!drawn || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
  e.preventDefault();
  cursor = Math.max(0, Math.min(drawnSteps(drawn).length - 1, cursor + (e.key === "ArrowRight" ? 1 : -1)));
  renderStrip(currentScope());
});

const currentScope = () => new Set(ALL.filter(inScope));
function render() {
  const idx = ALL.filter(inScope), scope = new Set(idx), s = stats(idx), lessons = scopedLessons(scope);
  renderScope(s); renderKpis(s, lessons); renderPatterns(s);
  if (tab === "themes") renderThemes(); else renderFiles(scope);
  renderLessons(lessons); renderStrip(scope);
}
render();
addEventListener("resize", () => renderStrip(currentScope()));
})();
