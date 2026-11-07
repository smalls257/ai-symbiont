/* "Is it getting better?": each recurring group per month as a rate per 10 sessions, a trend word, and the
   rate before and after the day the developer taught the agent about it.
   A raw count per month tracks how much the developer worked, so every cell is
   a rate and every number carries its unit (a column header, a legend, a tooltip with the raw counts). Sessions
   with no date are left out of the rates and counted in one sentence, never read as a zero month.
   Contract: window.SymbiontTrends.render(container, trends); `trends` is the page data's `trends` key
   (src/symbiont/service/trend_view.py). Tooltips are the page's delegated [data-tip] tooltip. */
(function () {
"use strict";
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/* A month with fewer sessions than this is read loosely (hatched). The same ten as the after-lesson rule. */
const THIN_SESSIONS = 10;
/* Shown order: what needs attention first. */
const TREND_RANK = {rising: 0, steady: 1, fading: 2, gone: 3};
const NO_DATES = "no dates";
/* Rows shown before the rest fold away: a project can have a hundred groups and the ones that matter sort first. */
const MAX_ROWS = 20;

const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const counted = (n, one) => n + " " + one + (n === 1 ? "" : "s");
const perTen = r => (r === null ? "unknown" : r.toFixed(1)) + " per 10 sessions";

function monthLabel(month) {
  const [year, number] = month.split("-");
  return {name: MONTH_NAMES[Number(number) - 1], year};
}
function dayLabel(iso) {
  const [year, month, day] = iso.split("-");
  return Number(day) + " " + MONTH_NAMES[Number(month) - 1] + " " + year;
}

const STYLE = `
.trn .mt{display:grid;gap:3px;align-items:center;overflow-x:auto}
.trn .h{font-size:.85rem;color:var(--mu);text-align:center;padding-bottom:.2rem;line-height:1.25}
.trn .h b{display:block;color:var(--tx);font-weight:600}
.trn .h small{display:block;font-size:.8rem}
.trn .l{font-size:.93rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-right:.6rem}
.trn .l .dot{display:inline-block;width:.7rem;height:.7rem;border-radius:50%;margin-right:.45rem}
.trn .l .dot.failure{background:var(--or)}
.trn .l .dot.correction{background:var(--cy)}
.trn .c{height:2.1rem;border-radius:.35rem;display:grid;place-items:center;font-size:.9rem;font-variant-numeric:tabular-nums}
.trn .c.z{color:var(--mu);opacity:.6}
.trn .c.thin{background-image:repeating-linear-gradient(45deg,rgba(236,240,248,.07) 0 3px,transparent 3px 7px)}
.trn .c.lesson{outline:2px solid var(--vi);outline-offset:-2px}
.trn .pill{display:inline-flex;font-size:.82rem;font-weight:650;padding:.08rem .55rem;border-radius:2rem;border:1px solid var(--line);color:var(--mu);white-space:nowrap}
.trn .pill.rising{color:var(--rd);border-color:rgba(244,84,84,.5)}
.trn .pill.resolved{color:var(--gr);border-color:rgba(84,222,124,.5)}
.trn .w{font-size:.88rem;padding-left:.6rem;white-space:nowrap}
.trn .lg{display:flex;gap:.4rem 1.2rem;flex-wrap:wrap;color:var(--mu);font-size:.88rem;align-items:center}
.trn .lg span{display:inline-flex;align-items:center;gap:.35rem}
.trn .lg i{display:inline-block;width:.9rem;height:.9rem;border-radius:.2rem}
.trn .lg i.lesson{background:none;outline:2px solid var(--vi);outline-offset:-2px}
.trn .lg i.thin{background-image:repeating-linear-gradient(45deg,rgba(236,240,248,.35) 0 2px,transparent 2px 5px)}
.trn summary{cursor:pointer;color:var(--vi);margin-top:.7rem}
.trn .note{color:var(--mu);font-size:.9rem;margin-top:.7rem}
.trn .taught-one{border-top:1px solid var(--line);padding:.8rem 0}
.trn .taught-one .t{font-weight:650}
.trn .bars{display:grid;grid-template-columns:9rem minmax(8rem,1fr) minmax(16rem,22rem);gap:.35rem .7rem;align-items:center;margin-top:.5rem}
.trn .bars .lab{font-size:.9rem;color:var(--mu)}
.trn .bars .track{height:1.1rem;background:rgba(236,240,248,.05);border-radius:.3rem}
.trn .bars .fill{height:100%;border-radius:.3rem;min-width:2px}
.trn .bars .fill.before{background:var(--or)}
.trn .bars .fill.after{background:var(--gr)}
.trn .bars .val{font-size:.9rem;font-variant-numeric:tabular-nums}
.trn .marker{grid-column:1/-1;color:var(--vi);font-size:.9rem;border-top:2px solid var(--vi);padding-top:.15rem;margin:.1rem 0}
`;

/* One row's trend: a pill with a word; gone says since when. */
function trendHtml(group) {
  if (group.trend === null) return '<span class="pill">' + NO_DATES + "</span>";
  if (group.trend === "gone") return '<span class="pill resolved">gone since ' + esc(dayLabel(group.last)) + "</span>";
  return '<span class="pill ' + (group.trend === "steady" ? "" : esc(group.trend)) + '">' + esc(group.trend) + "</span>";
}

function shadeStyle(group, cell, maxRate) {
  if (!cell.times) return "";
  const shade = group.kind === "correction" ? "var(--cy)" : "var(--or)";
  const share = Math.round(18 + 62 * Math.min(1, Math.sqrt(cell.per10 / maxRate)));
  return "background-color:color-mix(in srgb," + shade + " " + share + "%,transparent)";
}

function cellTip(group, month, cell) {
  const what = counted(cell.times, group.kind === "correction" ? "message" : "time");
  const lesson = group.taught && group.taught.month === month.month
    ? "<br>You taught the agent about this on " + esc(dayLabel(group.taught.on)) : "";
  const label = monthLabel(month.month);
  return "<b>" + label.name + " " + label.year + "</b>: " + what + " in " + counted(cell.sessions, "session")
    + "<br>" + perTen(cell.per10) + lesson;
}

function cellHtml(group, month, cell, maxRate) {
  const classes = ["c", cell.times ? "" : "z", month.sessions < THIN_SESSIONS ? "thin" : "",
    group.taught && group.taught.month === month.month ? "lesson" : ""].filter(Boolean).join(" ");
  return '<span class="' + classes + '" style="' + shadeStyle(group, cell, maxRate) + '" data-tip="'
    + esc(cellTip(group, month, cell)) + '">' + (cell.times ? cell.per10.toFixed(1) : "0") + "</span>";
}

function rowHtml(group, months, maxRate) {
  const cells = group.cells.map((cell, i) => cellHtml(group, months[i], cell, maxRate)).join("");
  return '<span class="l" title="' + esc(group.title) + '"><span class="dot ' + esc(group.kind) + '"></span>'
    + esc(group.title) + "</span>" + cells + '<span class="w">' + trendHtml(group) + "</span>";
}

function headerHtml(months) {
  const cols = months.map(m => {
    const label = monthLabel(m.month);
    return '<span class="h">' + label.name + "<small>" + label.year + "</small><b>" + counted(m.sessions, "session") + "</b></span>";
  }).join("");
  return '<span></span>' + cols + '<span class="h" style="text-align:left;padding-left:.6rem">direction</span>';
}

function byAttention(groups) {
  const rank = g => (g.trend === null ? 4 : TREND_RANK[g.trend]);
  const total = g => g.cells.reduce((sum, c) => sum + c.times, 0);
  return groups.slice().sort((a, b) => rank(a) - rank(b) || total(b) - total(a) || a.title.localeCompare(b.title));
}

function maxRateOf(groups) {
  const rates = groups.flatMap(g => g.cells.map(c => c.per10 || 0));
  return Math.max(0.1, ...rates);
}

function gridHtml(groups, trends, maxRate) {
  const columns = "minmax(14rem,1.8fr) repeat(" + trends.months.length + ",minmax(4.6rem,1fr)) 13rem";
  return '<div class="mt" style="grid-template-columns:' + columns + '">' + headerHtml(trends.months)
    + groups.map(g => rowHtml(g, trends.months, maxRate)).join("") + "</div>";
}

function tableHtml(trends) {
  const groups = byAttention(trends.groups), maxRate = maxRateOf(groups);
  const folded = groups.slice(MAX_ROWS);
  const more = folded.length ? "<details><summary>Show " + counted(folded.length, "more group") + "</summary>"
    + gridHtml(folded, trends, maxRate) + "</details>" : "";
  return gridHtml(groups.slice(0, MAX_ROWS), trends, maxRate) + more;
}

function legendHtml(anyTaught) {
  const lesson = anyTaught ? '<span><i class="lesson"></i>month you taught the agent about it</span>' : "";
  return '<div class="lg" style="margin-top:.7rem">'
    + "<span>Each cell: times per 10 sessions that month; hover for the raw counts. Column headers: sessions that month.</span>"
    + '<span><i style="background:var(--or)"></i>agent failures</span>'
    + '<span><i style="background:var(--cy)"></i>your corrections</span>'
    + '<span><i class="thin"></i>fewer than ' + THIN_SESSIONS + " sessions: read loosely</span>" + lesson + "</div>";
}

function undatedHtml(trends) {
  const times = trends.groups.reduce((sum, g) => sum + g.undatedTimes, 0);
  if (!trends.undatedSessions && !times) return "";
  return '<p class="note">' + counted(trends.undatedSessions, "session") + " had no date (their history carries no timestamps), so "
    + "they are left out of every rate; " + counted(times, "occurrence") + " in them are not placed in a month.</p>";
}

function barRow(label, name, window, scale) {
  const width = window.per10 === null ? 0 : Math.round(100 * window.per10 / scale);
  const tip = esc("<b>" + label + "</b>: " + counted(window.times, "time") + " in " + counted(window.sessions, "session")
    + "<br>" + perTen(window.per10));
  return '<span class="lab">' + esc(label) + '</span><span class="track" data-tip="' + tip + '"><span class="fill ' + name
    + '" style="display:block;width:' + width + '%"></span></span><span class="val">' + perTen(window.per10) + " ("
    + counted(window.times, "time") + " in " + counted(window.sessions, "session") + ")</span>";
}

function afterNote(taught) {
  if (taught.enough) return "";
  const need = THIN_SESSIONS - taught.after.sessions;
  return '<div class="note" style="grid-column:1/-1;margin:0">Too early to say: ' + counted(taught.after.sessions, "session")
    + " have run since the lesson; the after-rate counts once " + (need > 0 ? counted(need, "more session") + " have" : "10 sessions have") + " run.</div>";
}

function taughtHtml(group) {
  const taught = group.taught, on = dayLabel(taught.on);
  const scale = Math.max(0.1, taught.before.per10 || 0, taught.after.per10 || 0);
  return '<div class="taught-one"><div class="t">' + esc(group.title) + '</div><div class="bars">'
    + barRow("Before " + on, "before", taught.before, scale)
    + '<div class="marker">Lesson added ' + esc(on) + "</div>"
    + barRow("After " + on, "after", taught.after, scale) + afterNote(taught) + "</div></div>";
}

function lessonsHtml(trends) {
  const taught = trends.groups.filter(g => g.taught);
  const intro = '<h2 style="margin-top:1.4rem">Lessons you added</h2><p class="sub">The same rate, before and after the day you taught the agent. '
    + "Both bars share one scale: times per 10 sessions. The day itself counts as before.</p>";
  if (!taught.length) return intro + '<p class="mu">None yet. Use "Teach the agent" on a group in the inbox; it appears here with its before-rate.</p>';
  return intro + taught.map(taughtHtml).join("");
}

function render(container, trends) {
  const style = '<style>' + STYLE + "</style>";
  const head = "<h2>Is it getting better?</h2>"
    + '<p class="sub">Each group per month, as a rate: times per 10 sessions that month. Session counts swing, so raw counts would mislead.</p>';
  if (!trends.groups.length) {
    container.innerHTML = style + '<div class="trn">' + head + '<p class="mu">No group has come back in more than one session yet.</p>' + undatedHtml(trends) + "</div>";
    return;
  }
  const anyTaught = trends.groups.some(g => g.taught);
  container.innerHTML = style + '<div class="trn">' + head + tableHtml(trends) + legendHtml(anyTaught) + undatedHtml(trends) + lessonsHtml(trends) + "</div>";
}

window.SymbiontTrends = {render};
})();
