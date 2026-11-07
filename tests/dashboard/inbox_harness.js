// Loads the Inbox's model and rows in a bare context and prints what they decide.
// Run by test_inbox.py: `node inbox_harness.js <static dir>`.
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const sandbox = { window: {}, URLSearchParams };
for (const file of ["rename.js", "inbox_model.js", "inbox_rows.js", "inbox_noise.js", "tip.js"]) {
  vm.runInNewContext(fs.readFileSync(path.join(process.argv[2], file), "utf8"), sandbox);
}
const M = sandbox.window.SymbiontInboxModel;
const R = sandbox.window.SymbiontInboxRows;
const T = sandbox.window.SymbiontTip;
const N = sandbox.window.SymbiontInboxNoise;

const group = (key, over) => ({
  key, name: "Name of " + key, title: "pytest tests", groupedBecause: "Every card is pytest failing the same way.",
  kind: "failure", happened: "The agent ran pytest and it failed.", fixed: "Edited app.py.", verdict: "fixed in the code", fixShown: true,
  noise: null, noiseWords: "", sessions: 3, times: 4, recurring: true, trains: true, undatedSessions: 0, weekly: [["2026-W41", 2], ["2026-W43", 2]],
  undated: 0, first: "2026-10-05", last: "2026-10-20", cards: [{ firstWrong: "", costSteps: 0 }],
  trigger: { kind: "running", program: "pytest", path: "tests/e2e", words: "when running pytest on tests/e2e" }, ...over,
});
const warnings = [];
const warn = (m) => warnings.push(m);

const groups = [
  group("once", { recurring: false, trains: false, sessions: 1, times: 1, fixed: "Never fixed in this session.", fixShown: false, cards: [{ firstWrong: "", costSteps: 0 }] }),
  group("many"),
  group("noisy", { noise: "plain_retry", noiseWords: "passed when run again", times: 5, sessions: 2 }),
  group("noisy2", { noise: "plain_retry", noiseWords: "passed when run again", times: 2, sessions: 1 }),
  group("corr", { kind: "correction", fixShown: false, trains: false, fixed: "", title: "no, use uv", cards: [{ firstWrong: "Ran pip install", costSteps: 4, outcome: "developer_stepped_in", fixed: "" }], trigger: null }),
];
const archivedAll = groups.map((g) => g.noise ? g : { ...g, recurring: true });
const triageAll = Object.fromEntries(archivedAll.filter((g) => !g.noise).map((g) => [g.key, { state: "archived" }]));

const plain = M.sectionsOf(groups, {}, "all", "sessions");
const allArchived = M.sectionsOf(archivedAll, triageAll, "all", "sessions");
const renamed = M.displayName({ many: { name: "Mine" } }, groups[1]);
let badState = "";
try { M.tabOf({ many: { state: "weird" } }, groups[1]); } catch (e) { badState = e.message; }

const axis = M.weekAxis(groups);
const data = { stage: { facts: [1, 2, 3] }, incidents: { groups, topics: [1, 2] }, triage: {} };
const draft = M.teachDraft(groups[1], "n", true);
const neverFixed = M.teachDraft(groups[0], "n", true);
const corrDraft = M.teachDraft(groups[4], "n", false);
const corrDraftOwn = M.teachDraft(groups[4], "n", true);
const heldBack = M.teachDraft(group("held", { trains: false }), "n", true);
const emptyWhat = M.lessonRequest("demo", group("e", { happened: "The agent ran pytest and it failed." }), "when running pytest", "", "n");
const request = M.lessonRequest("demo", groups[1], draft.when, draft.what, "n");
const bare = M.lessonRequest("demo", groups[4], "", "", "Corrections group");
const rowFailure = R.rowHtml({ g: { ...groups[1], undatedSessions: 149 },  name: "A <b>name</b>", tab: "review", tri: { regressed: true }, series: M.seriesOf(groups[1], axis), weeks: axis });
const rowCorr = R.rowHtml({ g: groups[4], name: "Corr", tab: "archived", tri: { taught_on: "2026-11-01" }, series: [], weeks: axis });

let tooLong = "";
try { M.cleanName("x".repeat(81)); } catch (e) { tooLong = e.message; }

const worthy = [group("loud", { fixShown: false, sessions: 40 }), group("fixed", { fixShown: true, sessions: 3 })];
const rows = (n) => Array.from({ length: n }, (_, i) => i);
let orphan = null, orphanError = "";
try { orphan = M.sectionsOf(groups, { "failure:gone:exit 1": { state: "resolved" } }, "all", "worth"); } catch (e) { orphanError = e.message; }
const unmarked = group("unmarked", { sessions: 99 });
delete unmarked.fixShown;

const noiseCard = (value, words, sid, cmd) => ({ noise: value, noiseWords: words, sessionId: sid, step: 7, date: "2026-10-05", command: cmd, happened: "It exited 1." });
const noisy3 = [
  group("n1", { cards: [noiseCard("plain_retry", "passed when run again", "s1", "npm test <b>"), noiseCard("plain_retry", "passed when run again", "s1", "x".repeat(300))] }),
  group("n2", { kind: "correction", cards: [noiseCard("empty_correction", "an acknowledgment", "s2", "ok")] }),
];
const byReason = [{ reason: "passed when run again", count: 9 }, { reason: "an acknowledgment", count: 4 }, { reason: "mystery", count: 1 }];
let unknownReason = "";
try { N.rulesOf(byReason, [group("bad", { cards: [noiseCard("brand_new", "w", "s", "c")] })], "all"); } catch (e) { unknownReason = e.message; }
const rules = N.rulesOf(byReason, noisy3, "all");
const frictionView = { sessions: 40, frictions: [{ name: "Slow <i>CI</i>", description: "CI took ages", sessions: 4 }, { name: "Flaky", description: "Retries", sessions: 10 }] };
let badBadge = "";
try { M.badgeLabel("hot"); } catch (e) { badBadge = e.message; }

const bigCards = Array.from({ length: 30 }, (_, i) => noiseCard("plain_retry", "passed when run again", "s" + i, "cmd" + i));
const bigGroups = [group("big <1>", { name: "Evil <b>name</b>", noise: "plain_retry", noiseWords: "passed when run again", cards: bigCards, times: 30 }),
  ...["a", "b", "c"].map((k) => group("noise " + k, { noise: "plain_retry", noiseWords: "passed when run again", cards: [], times: 1 }))];
const bigRules = N.rulesOf([{ reason: "passed when run again", count: 30 }], bigGroups, "all");
const bigHtml = N.rulesHtml(bigRules, "", "demo");

console.log(JSON.stringify({
  bigHtml, bigGroupKeys: bigGroups.map((g) => g.key),
  badges: [M.badgeLabel("new"), M.badgeLabel("rising"), M.badgeLabel(null)], badBadge,
  verdicts: [M.verdictText({ verdict: "fixed in the code", verdictSentence: "Worth a look: it costs time." }), M.verdictText({ verdict: "fixed in the code", verdictSentence: null })],
  rules, unknownReason,
  rulesFailureOnly: N.rulesOf(byReason, noisy3, "failure").map((r) => r.reason),
  rulesHtml: N.rulesHtml(rules, M.seenOnceLine([group("a", { times: 2 }), group("b", { kind: "correction", times: 5 })]), "demo"),
  rulesEmpty: N.rulesHtml([], "", "demo"),
  seenOnce: [M.seenOnceLine([group("a", { times: 2 }), group("b", { times: 1 })]), M.seenOnceLine([])],
  frictions: M.frictionRows(frictionView), frictionsEmpty: M.frictionRows({ sessions: 0, frictions: [] }),
  frictionHtml: R.frictionHtml(M.frictionRows(frictionView)),
  tilesWithRequests: M.tilesOf({ ...data, topicView: { requests: 12 } }).map((t) => t.sub),
  rowOpen: R.rowHtml({ g: { ...groups[1], badge: "rising", verdictSentence: "Worth a look: slow." }, project: "my proj", name: "n", tab: "review", tri: {}, series: [], weeks: axis }),
  worth: M.sectionsOf(worthy, {}, "all", "worth").review.map((g) => g.key),
  pages: { twenty: M.pageOf(rows(20), false), expanded: M.pageOf(rows(20), true), three: M.pageOf(rows(3), false), pageSize: M.REVIEW_PAGE },
  scope: ["struggle", "inbox", "topics", "trends", "context", "replay"].map((v) => M.scopeVisible(v, 1)),
  scopeByStage: [0, 1, 2, 3].map((n) => M.scopeVisible("struggle", n)),
  scopeViewsOnOtherStages: ["context", "replay"].flatMap((v) => [0, 1, 2, 3].map((n) => M.scopeVisible(v, n))),
  focusAfterExpand: M.focusAfterExpand(M.REVIEW_PAGE),
  sortOptions: Object.keys(M.SORT_WORDS), sortWords: M.SORT_WORDS, defaultSort: M.DEFAULT_SORT,
  unmarkedWorth: M.sectionsOf([unmarked, group("fixedlow", { sessions: 1 })], {}, "all", "worth").review.map((g) => g.key),
  orphan, orphanThrew: orphanError,
  orphanPlain: M.sectionsOf(groups, {}, "all", "worth"),
  plain: Object.fromEntries(Object.entries(plain).map(([k, v]) => [k, v.map((g) => g.key)])),
  allArchived: Object.fromEntries(Object.entries(allArchived).map(([k, v]) => [k, v.map((g) => g.key)])),
  correctionsOnly: M.sectionsOf(groups, {}, "correction", "sessions").review.map((g) => g.key),
  renamed, generated: M.displayName({}, groups[1]), badState,
  tiles: M.tilesOf(data),
  axisKeys: axis.map((w) => w.key),
  series: M.seriesOf(groups[1], axis),
  draft, neverFixed, corrDraft, corrDraftOwn, request, bare, emptyWhat,
  teachNotes: { trains: M.teachNote(draft), held: M.teachNote(heldBack) },
  archive: M.ARCHIVE_CHOICES.map((c) => c.body),
  archiveLabels: M.ARCHIVE_CHOICES.map((c) => c.label),
  archiveOn: M.archiveChoices(new Date(2026, 10, 7)).map((c) => c.detail),
  views: ["", "inbox", "topics", "trends", "struggle", "context", "replay", "nope"].map((v) => M.viewFrom(v ? "?view=" + v : "", warn)),
  warnings, tooLong, trimmed: M.cleanName("  Flaky  "),
  tips: [
    "<b>Week of Oct 5</b><br>1 time",
    "Oct 5: <img src=x onerror=window.__x=1>",
    '<b onclick="window.__x=1">x</b>',
    "<span class=m>quiet</span> <script>1</script>",
    "&lt;img src=x&gt; already escaped",
  ].map((t) => T.safe(t)),
  rowEvil: R.rowHtml({ g: group("e", { kind: "x\" onmouseover=\"window.__x=1" }), name: "n", tab: "review", tri: {}, series: [], weeks: axis }),
  rowFailure, rowCorr, tilesHtml: R.tilesHtml(M.tilesOf(data)),
}));
