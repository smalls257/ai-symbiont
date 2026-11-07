// Loads heatcell.js in a bare context and prints what it decides. Run by test_heatcell.py: `node heatcell_harness.js <path to heatcell.js>`.
const fs = require("fs");
const vm = require("vm");

const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const H = sandbox.window.SymbiontHeat;

const themes = [["auth", 120], ["build", 60], ["docs", 3], ["cli", 180]];
const column = (allPattern, perTheme) => themes.map(([theme, n], i) => H.compareCell({
  theme, themeSessions: n, themePattern: perTheme[i], allSessions: 363, allPattern,
}));
console.log(JSON.stringify({
  rareColumn: column(1, [1, 0, 0, 0]),
  commonColumn: column(100, [60, 5, 0, 20]),
  tinyTheme: H.compareCell({ theme: "docs", themeSessions: 3, themePattern: 0, allSessions: 363, allPattern: 20 }),
  labels: [H.shareLabel(1, 363), H.shareLabel(2, 363), H.shareLabel(0, 363), H.shareLabel(50, 363), H.shareLabel(0, 0)],
}));
