// Loads the Inbox's model and rows in a bare context and prints what they decide.
// Run by test_inbox.py: `node inbox_harness.js <static dir>`.
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const sandbox = { window: {}, URLSearchParams };
for (const file of ["inbox_model.js", "inbox_rows.js"]) {
  vm.runInNewContext(fs.readFileSync(path.join(process.argv[2], file), "utf8"), sandbox);
}
const M = sandbox.window.SymbiontInboxModel;
const R = sandbox.window.SymbiontInboxRows;

const group = (key, over) => ({
  key, name: "Name of " + key, title: "pytest tests", groupedBecause: "Every card is pytest failing the same way.",
  kind: "failure", happened: "The agent ran pytest and it failed.", fixed: "Edited app.py.", verdict: "fixed in the code",
  noise: null, noiseWords: "", sessions: 3, times: 4, recurring: true, weekly: [["2026-W41", 2], ["2026-W43", 2]],
  undated: 0, first: "2026-10-05", last: "2026-10-20", cards: [{ firstWrong: "", costSteps: 0 }],
  trigger: { kind: "running", program: "pytest", path: "tests/e2e", words: "when running pytest on tests/e2e" }, ...over,
});
const warnings = [];
const warn = (m) => warnings.push(m);

const groups = [
  group("once", { recurring: false, sessions: 1, times: 1, fixed: "" }),
  group("many"),
  group("noisy", { noise: "plain_retry", noiseWords: "passed when run again", times: 5, sessions: 2 }),
  group("noisy2", { noise: "plain_retry", noiseWords: "passed when run again", times: 2, sessions: 1 }),
  group("corr", { kind: "correction", title: "no, use uv", cards: [{ firstWrong: "Ran pip install", costSteps: 4 }], trigger: null }),
];
const archivedAll = groups.map((g) => g.noise ? g : { ...g, recurring: true });
const triageAll = Object.fromEntries(archivedAll.filter((g) => !g.noise).map((g) => [g.key, { state: "archived" }]));

const plain = M.sectionsOf(groups, {}, "all", "sessions");
const allArchived = M.sectionsOf(archivedAll, triageAll, "all", "sessions");
const renamed = M.displayName({ many: { name: "Mine" } }, groups[1]);
let badState = "";
try { M.tabOf({ many: { state: "weird" } }, groups[1]); } catch (e) { badState = e.message; }

const axis = M.weekAxis(groups);
const data = { sessions: [1, 2, 3], incidents: { groups, topics: [1, 2] }, triage: {} };
const draft = M.teachDraft(groups[1], "n");
const corrDraft = M.teachDraft(groups[4], "n");
const request = M.lessonRequest("demo", groups[1], draft.when, draft.what, "n");
const bare = M.lessonRequest("demo", groups[4], "", "", "Corrections group");
const rowFailure = R.rowHtml({ g: groups[1], name: "A <b>name</b>", tab: "review", tri: { regressed: true }, series: M.seriesOf(groups[1], axis), weeks: axis });
const rowCorr = R.rowHtml({ g: groups[4], name: "Corr", tab: "archived", tri: { taught_on: "2026-11-01" }, series: [], weeks: axis });

let tooLong = "";
try { M.cleanName("x".repeat(81)); } catch (e) { tooLong = e.message; }

console.log(JSON.stringify({
  plain: Object.fromEntries(Object.entries(plain).map(([k, v]) => [k, v.map((g) => g.key)])),
  allArchived: Object.fromEntries(Object.entries(allArchived).map(([k, v]) => [k, v.map((g) => g.key)])),
  correctionsOnly: M.sectionsOf(groups, {}, "correction", "sessions").review.map((g) => g.key),
  noiseReasons: M.noiseReasons(plain.noise),
  renamed, generated: M.displayName({}, groups[1]), badState,
  tiles: M.tilesOf(data),
  axisKeys: axis.map((w) => w.key),
  series: M.seriesOf(groups[1], axis),
  draft, corrDraft, request, bare,
  archive: M.ARCHIVE_CHOICES.map((c) => c.body),
  views: ["", "inbox", "topics", "trends", "struggle", "context", "replay", "nope"].map((v) => M.viewFrom(v ? "?view=" + v : "", warn)),
  warnings, tooLong, trimmed: M.cleanName("  Flaky  "),
  rowFailure, rowCorr, tilesHtml: R.tilesHtml(M.tilesOf(data)),
}));
