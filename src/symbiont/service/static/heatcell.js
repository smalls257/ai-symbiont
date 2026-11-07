/* When the theme x pattern map may color a cell. Pure functions, no DOM, so node can test them.
   Violation prevented: Paper Tiger. A pattern seen in one session of 363 gave every theme with zero such sessions
   the deepest blue ("less common than usual"), so one session painted a whole column and the map said nothing true.
   A cell is compared only when the usual rate is real and the theme is big enough for a zero to mean something. */
(function () {
"use strict";
/* A pattern seen in fewer sessions overall has no "usual rate" worth comparing against. */
const MIN_PATTERN_SESSIONS = 5;
/* A theme expected to show the pattern in under 2 sessions cannot look "less common" by showing it in none. */
const MIN_EXPECTED = 2;

const counted = (n, noun) => n + " " + noun + (n === 1 ? "" : "s");

/* {compared: true, ratio} or {compared: false, reason}: the reason is the tooltip line, plain prose. */
function compareCell(c) {
  if (c.allPattern < MIN_PATTERN_SESSIONS) return {compared: false, reason: "Too rare to compare: " + counted(c.allPattern, "session") + " in all"};
  const usual = c.allPattern / c.allSessions;
  if (usual * c.themeSessions < MIN_EXPECTED) return {compared: false, reason: "Too few sessions in " + c.theme + " to compare"};
  return {compared: true, ratio: (c.themePattern / c.themeSessions) / usual};
}

/* A share that rounds to 0% but is not none shows the count: "0%" would read as "never". */
function shareLabel(count, total) {
  const rounded = total ? Math.round(100 * count / total) : 0;
  return count > 0 && rounded === 0 ? counted(count, "session") : rounded + "%";
}

window.SymbiontHeat = {MIN_PATTERN_SESSIONS, MIN_EXPECTED, compareCell, shareLabel};
})();
