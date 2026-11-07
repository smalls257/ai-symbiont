/* The side column of "Is it getting better?": a before and after found in the history, and the lessons the
   developer added. Contract: window.SymbiontTrendsSide.html(trends, fmt) returns the column's markup;
   `fmt` is trends.js's {esc, counted, perTen, dayLabel, groupHref}. Every data string goes through fmt.esc. */
(function () {
"use strict";
/* The same ten sessions as trends.js and core/trends.py: fewer cannot show whether a lesson worked. */
const ENOUGH_SESSIONS = 10;

const STYLE = `
.trn .pg{display:grid;grid-template-columns:minmax(0,1fr) 30rem;gap:1.2rem;align-items:start}
.trn .side{display:flex;flex-direction:column;gap:1.2rem;position:sticky;top:5.2rem}
.trn .ba{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:.8rem}
.trn .ba div{border:1px solid var(--line);border-radius:.7rem;padding:.7rem .9rem}
.trn .ba b{display:block;font-size:2.2rem;line-height:1.05;font-variant-numeric:tabular-nums}
.trn .ba span{color:var(--mu);font-size:.9rem}
.trn .ba .bef b{color:var(--or)}
.trn .ba .aft b{color:var(--gr)}
.trn .caveat{color:var(--mu);font-size:.9rem;margin-top:.7rem;border-top:1px dashed var(--line);padding-top:.6rem}
.trn .caveat a,.trn .panel .mu a{color:var(--vi)}
.trn .taught a.one{display:block;text-decoration:none;padding:.5rem 0;border-top:1px solid var(--line)}
.trn .taught a.one small{display:block;color:var(--mu)}
@media (max-width:1100px){.trn .pg{grid-template-columns:minmax(0,1fr)}.trn .side{position:static}}
`;

const CAVEAT = "Read it with care: fewer sessions, or a different kind of work, can also make a group go quiet. "
  + "The rate per 10 sessions is the fair comparison; a lesson counts as working only when the after-rate stays at or near zero "
  + "over at least " + ENOUGH_SESSIONS + " sessions.";

function naturalHtml(found, fmt) {
  if (!found) return "";
  const what = found.kind === "correction" ? "message" : "failure", day = fmt.dayLabel(found.last);
  const span = found.first === found.last ? fmt.dayLabel(found.first) : fmt.dayLabel(found.first) + " to " + day;
  return '<section class="panel"><h2>A before and after you already have</h2>'
    + '<p class="sub">Not taught through symbiont: this group went quiet on its own. This is what the comparison looks like once you teach something.</p>'
    + '<div style="font-weight:650">' + fmt.esc(found.title) + "</div>"
    + '<div class="ba"><div class="bef"><b>' + found.before.times + "</b><span>" + fmt.esc(fmt.counted(found.before.times, what))
    + " in " + fmt.esc(fmt.counted(found.sessionsWithGroup, "session")) + ", " + fmt.esc(span) + " (" + fmt.esc(fmt.perTen(found.before.per10)) + ")</span></div>"
    + '<div class="aft"><b>' + found.after.times + "</b><span>" + fmt.esc(fmt.counted(found.after.times, what)) + " in "
    + fmt.esc(fmt.counted(found.after.sessions, "session")) + " after " + fmt.esc(day) + " (" + fmt.esc(fmt.perTen(found.after.per10)) + ")</span></div></div>"
    + '<div class="caveat">' + CAVEAT + ' <a data-route href="' + fmt.esc(fmt.groupHref(found.key)) + '">Open the group →</a></div></section>';
}

function afterWords(taught, fmt) {
  if (taught.enough) return fmt.perTen(taught.after.per10);
  const need = ENOUGH_SESSIONS - taught.after.sessions;
  return "waiting for " + (need >= ENOUGH_SESSIONS ? ENOUGH_SESSIONS : need + " more") + " sessions";
}

function lessonHtml(group, fmt) {
  const taught = group.taught;
  return '<a class="one" data-route href="' + fmt.esc(fmt.groupHref(group.key)) + '">' + fmt.esc(taught.lesson || group.title)
    + "<small>added " + fmt.esc(fmt.dayLabel(taught.on)) + " · before: " + fmt.esc(fmt.perTen(taught.before.per10))
    + " · after: " + fmt.esc(afterWords(taught, fmt)) + "</small></a>";
}

function lessonsHtml(trends, fmt) {
  const taught = trends.groups.filter(g => g.taught);
  const body = taught.length ? taught.map(g => lessonHtml(g, fmt)).join("")
    : '<p class="mu">None yet. Use "Teach the agent" on any group in the inbox; it appears here with its before-rate, and the after-rate fills in as sessions run.</p>';
  return '<section class="panel taught"><h2>Lessons you added</h2><p class="sub">After a lesson, the same rate is compared before and after, once '
    + ENOUGH_SESSIONS + " sessions have run. The day itself counts as before.</p>" + body + "</section>";
}

window.SymbiontTrendsSide = {
  style: STYLE,
  html: (trends, fmt) => '<aside class="side">' + naturalHtml(trends.natural, fmt) + lessonsHtml(trends, fmt) + "</aside>"
};
})();
