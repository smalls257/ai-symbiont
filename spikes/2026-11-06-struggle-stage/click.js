(function () {
"use strict";
/* Mockup: one selection (theme, pattern) scopes every panel on the stage. */
const D = window.D, C = D.click, F = C.facts;
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = n => Math.round(n).toLocaleString("en-US");
const pct = (a, b) => b ? Math.round(100 * a / b) : 0;
const tip = $("tip");
document.addEventListener("pointermove", e => {
  const t = e.target.closest("[data-tip]");
  if (!t) { tip.style.display = "none"; return; }
  tip.innerHTML = t.dataset.tip; tip.style.display = "block";
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 360) + "px"; tip.style.top = (e.clientY + 14) + "px";
});

const PAT = Object.fromEntries(D.themes.patterns.map(p => [p.id, p]));
const PIDS = D.themes.patterns.map(p => p.id);
const SHORT = {test_miss:"Tests not found",inline_trial:"Inline trial",scratch_debug:"Scratch debug",edit_thrash:"Edit thrash",api_misuse:"Wrong API",probe_miss:"Wrong place",rerun:"Re-running",never_fixed:"Ended failing"};
const ALL = F.map((_, i) => i);
const sel = {theme: null, pattern: null};
const inScope = i => (!sel.theme || F[i].themes.includes(sel.theme)) && (!sel.pattern || F[i].patterns.includes(sel.pattern));

function stats(idxs) {
  const o = {fixed:0, corrected:0, total:0}, pats = Object.fromEntries(PIDS.map(p => [p, 0]));
  let turns = 0, struggled = 0;
  idxs.forEach(i => { const f = F[i]; turns += f.turns; if (f.struggled) struggled++;
    Object.entries(f.outcomes).forEach(([k, v]) => { o.total += v; if (k === "fixed") o.fixed += v; if (k === "corrected") o.corrected += v; });
    f.patterns.forEach(p => pats[p]++); });
  return {n: idxs.length, turns, struggled, fixed: o.fixed, corrected: o.corrected, failures: o.total, pats};
}
const ALLS = stats(ALL);
const isScratch = t => /^(reproduce|comprehensive|debug)\w*\.py$/.test(t.target);

/* themes, ranked once for the whole history: frequent first, then the most unusual struggle */
const THEMES = (() => {
  const base = ALLS.struggled / ALLS.n;
  const rows = C.themeWords.map(w => { const idx = ALL.filter(i => F[i].themes.includes(w)); const s = stats(idx);
    return {w, idx, s, rate: s.struggled / s.n}; }).filter(r => r.s.n >= 60);
  return rows.sort((a, b) => Math.abs(b.rate - base) - Math.abs(a.rate - base)).slice(0, 16).sort((a, b) => b.rate - a.rate);
})();

function setSel(theme, pattern) {
  sel.theme = theme; sel.pattern = pattern; render();
}
function toggle(kind, v) { setSel(kind === "theme" ? (sel.theme === v ? null : v) : sel.theme, kind === "pattern" ? (sel.pattern === v ? null : v) : sel.pattern); }

function renderScope(scoped) {
  const chips = [];
  if (sel.theme) chips.push(["theme", sel.theme]);
  if (sel.pattern) chips.push(["pattern", SHORT[sel.pattern]]);
  $("scope").innerHTML = chips.length
    ? "Scope " + chips.map(c => '<span class="chip">' + esc(c[1]) + '<button data-clear="' + c[0] + '" aria-label="Clear ' + esc(c[1]) + '">✕</button></span>').join("") + '<span>' + fmt(scoped.n) + ' sessions</span>'
    : '<span>All ' + fmt(ALLS.n) + ' sessions · click a theme, pattern or cell to scope</span>';
  $("scope").querySelectorAll("[data-clear]").forEach(b => b.onclick = () => b.dataset.clear === "theme" ? setSel(null, sel.pattern) : setSel(sel.theme, null));
}

function renderKpis(s, lessons) {
  const scoped = sel.theme || sel.pattern;
  const of = (v, all, unit) => scoped ? '<span class="of">of ' + all + unit + ' across all sessions</span>' : '<span class="of">' + v + '</span>';
  const hrs = s.turns * C.minutesPerTurn / 60, allHrs = ALLS.turns * C.minutesPerTurn / 60;
  $("kpis").innerHTML = [
    [fmt(s.turns), "agent turns lost", scoped ? of("", fmt(ALLS.turns), "") : '<span class="of">from a failure to the next pass of the same program</span>', "var(--rd)"],
    ["~" + fmt(hrs) + " h", "of working time lost", scoped ? of("", "~" + fmt(allHrs), " h") : '<span class="of">estimated at ' + C.minutesPerTurn + ' min per turn</span>', "var(--or)"],
    [fmt(lessons.length), "lessons ready", scoped ? of("", fmt(ALL_LESSONS), "") : '<span class="of">a known fix, seen in 2+ sessions</span>', "var(--vi)"],
    [pct(s.fixed + s.corrected, s.failures) + "%", "of failures ended in a known fix", '<span class="of">' + fmt(s.fixed) + " code edits, " + fmt(s.corrected) + " corrected commands" + (scoped ? " (all: " + pct(ALLS.fixed + ALLS.corrected, ALLS.failures) + "%)" : "") + "</span>", "var(--gr)"],
  ].map(k => '<div class="panel kpi"><div class="num" style="color:' + k[3] + '">' + k[0] + '</div><div class="lbl">' + k[1] + k[2] + "</div></div>").join("");
}

function renderPatterns(s) {
  const rows = PIDS.map(p => ({p, share: s.pats[p] / Math.max(1, s.n), all: ALLS.pats[p] / ALLS.n})).sort((a, b) => b.share - a.share);
  const mx = Math.max(...rows.map(r => Math.max(r.share, r.all)), 0.01);
  $("pats").innerHTML = rows.map(r => { const P = PAT[r.p], quiet = /nothing to teach|human/.test(P.action);
    return '<div class="ptn' + (quiet ? " quiet" : "") + (sel.pattern === r.p ? " sel" : "") + '" data-p="' + r.p + '" tabindex="0" data-tip="<b>' + esc(P.name) + '</b><br>' + esc(P.means) + ((sel.theme) ? "<br>all sessions: " + Math.round(r.all * 100) + "%" : "") + '">'
      + '<div class="nm">' + esc(P.name) + '</div><div class="v">' + Math.round(r.share * 100) + '<small>%</small></div>'
      + '<div class="tr"><i style="width:' + (100 * r.share / mx) + '%"></i>' + (sel.theme ? '<b style="left:' + (100 * r.all / mx) + '%"></b>' : "") + '</div>'
      + '<div class="act">→ <em>' + esc(P.action) + "</em></div></div>"; }).join("");
  $("pats").querySelectorAll(".ptn").forEach(d => { d.onclick = () => toggle("pattern", d.dataset.p); d.onkeydown = e => { if (e.key === "Enter") d.onclick(); }; });
}

function divColor(r) {
  if (r >= 1.8) return "#ff8c40"; if (r >= 1.35) return "#b96a3e"; if (r >= 1.12) return "#6e4f4a";
  if (r <= 0.55) return "#3f86b8"; if (r <= 0.75) return "#35617f"; if (r <= 0.9) return "#33475a"; return "#3a3550";
}
let tab = "themes";
function renderThemes() {
  $("mapTitle").textContent = "What was being worked on";
  const base = ALLS.struggled / ALLS.n;
  $("mapSub").innerHTML = "Themes from the tasks, in the codebase's own words: struggle rate against the " + Math.round(base * 100) + "% average, then which patterns are unusually common. Click a theme, a column or a cell.";
  let h = '<div class="ch"></div><div class="ch">struggle<br>vs average</div>' + PIDS.map(p => '<div class="ch p' + (sel.pattern === p ? " sel" : "") + '" data-p="' + p + '">' + SHORT[p].replace(" ", "<br>") + "</div>").join("");
  THEMES.forEach(r => { const d = r.rate - base, w = Math.min(100, Math.abs(d) / 0.2 * 100), on = sel.theme === r.w;
    h += '<div class="rl' + (on ? " sel" : "") + '" data-t="' + esc(r.w) + '" data-tip="<b>' + esc(r.w) + "</b><br>" + fmt(r.s.n) + " sessions<br>e.g. " + esc((C.titles[r.w] || [""])[0]) + '">' + esc(r.w) + "<small>" + fmt(r.s.n) + "</small></div>";
    h += '<div class="rate" data-t="' + esc(r.w) + '" data-tip="' + Math.round(r.rate * 100) + "% of " + esc(r.w) + " sessions struggled (average " + Math.round(base * 100) + '%)"><i class="' + (d >= 0 ? "up" : "dn") + '" style="width:' + w + '%"></i></div>';
    PIDS.forEach(p => { const v = r.s.pats[p] / r.s.n, all = ALLS.pats[p] / ALLS.n, L = all ? v / all : 1;
      const isSel = on && sel.pattern === p, dim = (sel.theme && !on) || (sel.pattern && sel.pattern !== p);
      h += '<div class="c' + (isSel ? " sel" : "") + (dim && !isSel ? " dim" : "") + '" tabindex="0" data-t="' + esc(r.w) + '" data-p="' + p + '" style="background:' + divColor(L) + '" data-tip="<b>' + Math.round(v * 100) + "% of " + esc(r.w) + " sessions</b><br>" + esc(SHORT[p]) + " (usual: " + Math.round(all * 100) + "%)<br>" + (L >= 1 ? L.toFixed(1) + "× the usual rate" : "less common than usual") + '"></div>'; });
  });
  $("hm").style.gridTemplateColumns = "minmax(10.5rem,1.4fr) 6rem repeat(" + PIDS.length + ",1fr)";
  $("hm").innerHTML = h;
  $("hm").querySelectorAll(".rl[data-t],.rate[data-t]").forEach(e => e.onclick = () => toggle("theme", e.dataset.t));
  $("hm").querySelectorAll(".ch.p").forEach(e => e.onclick = () => toggle("pattern", e.dataset.p));
  $("hm").querySelectorAll(".c[data-t]").forEach(e => { e.onclick = () => (sel.theme === e.dataset.t && sel.pattern === e.dataset.p) ? setSel(null, null) : setSel(e.dataset.t, e.dataset.p); e.onkeydown = ev => { if (ev.key === "Enter") e.onclick(); }; });
  const sw = c => '<span style="background:' + c + '"></span>';
  $("hmLegend").innerHTML = '<span>Pattern, compared with all sessions:</span><span>less<span class="sw">' + ["#3f86b8","#35617f","#33475a","#3a3550","#6e4f4a","#b96a3e","#ff8c40"].map(sw).join("") + '</span>more</span><span><span class="dot" style="background:var(--rd)"></span>struggles more than average</span><span><span class="dot" style="background:var(--cy)"></span>less</span>';
}
function renderFiles() {
  $("mapTitle").textContent = "Where in the repo, month by month";
  $("mapSub").textContent = "Share of each month's sessions that struggled on the file." + (sel.theme || sel.pattern ? " Not scoped by your selection in this mockup." : "");
  const M = D.months, ramp = v => v === 0 ? "rgba(236,240,248,.05)" : ["#4a3470","#7a4a6a","#a95c5a","#d9734a","#ff8c40"][Math.min(4, [0.05,0.12,0.2,0.35].filter(c => v >= c).length)];
  let h = '<div class="ch"></div>' + M.map((m, i) => '<div class="ch">' + (i % 6 === 0 ? m.slice(2) : "") + "</div>").join("") + '<div class="ch">sessions</div>';
  D.heat.forEach(r => { h += '<div class="rl mono" title="' + esc(r.file) + '">' + esc(r.file.replace(/^sqlglot\//, "")) + "</div>";
    r.cells.forEach((c, i) => { h += '<div class="c" style="background:' + ramp(c.share) + '" data-tip="<b>' + (c.sessions ? Math.round(c.share * 100) + "% of sessions" : "no struggle") + "</b><br>" + esc(r.file) + ", " + M[i] + '"></div>'; });
    h += '<div class="rl" style="text-align:right">' + r.sessions + "</div>"; });
  $("hm").style.gridTemplateColumns = "minmax(12rem,1.3fr) repeat(" + M.length + ",1fr) 3.2rem"; $("hm").innerHTML = h;
  $("hmLegend").innerHTML = "<span>A band that never cools is a hard area; one hot cell is a one-off.</span>";
}
$("tThemes").onclick = () => { tab = "themes"; $("tThemes").setAttribute("aria-pressed", true); $("tFiles").setAttribute("aria-pressed", false); renderThemes(); };
$("tFiles").onclick = () => { tab = "files"; $("tFiles").setAttribute("aria-pressed", true); $("tThemes").setAttribute("aria-pressed", false); renderFiles(); };

const LESSONS = C.traps.filter(t => !isScratch(t));
const ALL_LESSONS = LESSONS.length;
const broke = b => ({"exit 4": "a usage error", "exit 5": "no tests collected"}[b] || b);
function scopedLessons(scope) {
  return LESSONS.map(t => ({t, n: t.sessions.filter(i => scope.has(i)).length})).filter(x => x.n > 0).sort((a, b) => b.n - a.n);
}
function renderLessons(list) {
  const scoped = sel.theme || sel.pattern;
  $("lesSub").textContent = scoped ? "Lessons whose trap shows up in this scope, most sessions first" : "A known fix (a code edit or a corrected command), came back in 2+ sessions";
  $("les").innerHTML = list.length ? list.slice(0, 8).map(({t, n}) => { const tg = t.target && t.target !== "-" ? t.target : "inline script";
    return '<li><button data-tip="' + esc(t.occurrences + " times in " + t.sessions.length + " sessions overall") + '"><span class="t">' + esc(t.program + " " + tg) + " → " + esc(broke(t.broke)) + '</span><span class="big" style="color:var(--vi)">' + n + "<small>" + (scoped ? "of " + t.sessions.length + " sessions" : "sessions") + '</small></span><span class="why">fixed by: ' + esc(t.fix.replace(/`cd \/workspace\/\S+ && /, "`")) + "</span></button></li>"; }).join("")
    : '<li class="empty">No lesson-grade trap in this scope: the struggle here never ended in a real fix.</li>';
  const held = C.traps.filter(isScratch).length;
  $("held").textContent = held + " more held back overall: they fix the agent's own scratch files.";
}

function renderStrip(scope) {
  const cand = Object.entries(C.strips).filter(([i]) => scope.has(+i)).sort((a, b) => b[1].burst - a[1].burst)[0];
  const svg = $("stripsvg");
  if (!cand) { $("stripSub").textContent = "No example session drawn for this scope."; svg.innerHTML = ""; return; }
  const st = cand[1], S = st.steps, last = S[S.length - 1][0];
  $("stripSub").textContent = (sel.theme || sel.pattern ? "The densest struggle in this scope" : "The densest struggle overall") + " (task " + st.task + "), " + S.length + " steps. Shaded: three or more failures within ten steps.";
  const b = svg.getBoundingClientRect(), W = Math.round(b.width) || 1600, H = Math.round(b.height) || 200;
  const X0 = 150, X1 = W - 20, xs = s => X0 + (s / last) * (X1 - X0), lane = {u: H * 0.2, e: H * 0.5, s: H * 0.5, f: H * 0.8, p: H * 0.8};
  const fails = S.filter(s => s[1] === "f").map(s => s[0]), bursts = [];
  fails.forEach(s => { const w = fails.filter(f => f >= s && f < s + 10); if (w.length >= 3) { const p = bursts[bursts.length - 1]; if (p && s <= p[1]) p[1] = Math.max(p[1], w[w.length - 1]); else bursts.push([s, w[w.length - 1]]); } });
  let h = bursts.map(([a, z]) => '<rect x="' + (xs(a) - 8) + '" y="4" width="' + (xs(z) - xs(a) + 16) + '" height="' + (H - 26) + '" rx="8" fill="rgba(244,84,84,.12)"/>').join("");
  [["you", lane.u], ["edits", lane.e], ["commands", lane.f]].forEach(([n, y]) => { h += '<text x="' + (X0 - 16) + '" y="' + (y + 5) + '" text-anchor="end" font-size="15" fill="#8c94ac">' + n + '</text><line x1="' + X0 + '" x2="' + X1 + '" y1="' + y + '" y2="' + y + '" stroke="rgba(236,240,248,.1)" stroke-width="2"/>'; });
  const col = {u: "#5cc8ff", e: "#ff8c40", f: "#f45454", p: "#8c94ac"}, what = {u: "you wrote", e: "edit in the codebase", s: "edit to a scratch file", f: "command failed", p: "command passed"};
  S.forEach(([step, ty, label]) => { const t = esc(label) + "<br>" + what[ty] + ", step " + step;
    h += ty === "s" ? '<circle cx="' + xs(step) + '" cy="' + lane[ty] + '" r="5" fill="none" stroke="#8c94ac" stroke-width="2" data-tip="' + t + '"/>'
      : '<circle cx="' + xs(step) + '" cy="' + lane[ty] + '" r="' + (ty === "p" ? 4 : 6) + '" fill="' + col[ty] + '" stroke="#16112a" stroke-width="2" data-tip="' + t + '"/>'; });
  [["failed", "#f45454"], ["passed", "#8c94ac"], ["edit in codebase", "#ff8c40"], ["you", "#5cc8ff"]].forEach((l, i) => { h += '<circle cx="' + (X0 + i * 150) + '" cy="' + (H - 6) + '" r="5" fill="' + l[1] + '"/><text x="' + (X0 + i * 150 + 10) + '" y="' + (H - 1) + '" font-size="13" fill="#8c94ac">' + l[0] + "</text>"; });
  h += '<circle cx="' + (X0 + 600) + '" cy="' + (H - 6) + '" r="4" fill="none" stroke="#8c94ac" stroke-width="2"/><text x="' + (X0 + 610) + '" y="' + (H - 1) + '" font-size="13" fill="#8c94ac">scratch-file edit</text>';
  svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.innerHTML = h;
}

function render() {
  const idx = ALL.filter(inScope), scope = new Set(idx), s = stats(idx), lessons = scopedLessons(scope);
  renderScope(s); renderKpis(s, lessons); renderPatterns(s);
  tab === "themes" ? renderThemes() : renderFiles();
  renderLessons(lessons); renderStrip(scope);
}
render();
addEventListener("resize", () => renderStrip(new Set(ALL.filter(inScope))));
})();
