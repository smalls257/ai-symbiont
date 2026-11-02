# Core v3 (v3.1): amendment 3, stopped early by owner decision

Dated 2026-11-02. **Stopped early by owner decision (5080 heat) at 23:40 on 2026-11-01; 37 of 60 blocks complete** (163 runs). The task containers ran on the 5080, so shutting it down ended the test. It changes no task, arm, measure or rule; the Monday cutoff is not reached [measured].

- **Analysis.** The completed blocks are scored exactly per the prereg: V3 minus P solve rate, paired by task, 95% bootstrap interval (seed 20261101), with the secondaries (code-level pain points, steps, reasoning length). The result is labeled stopped-early and the words stay "no detected difference" unless an interval excludes 0 as the prereg states [established].
- **Disclosed: an unplanned, owner-requested peek at about 23:35**, at 36 complete blocks: plain 0.097, v3.1 0.056, difference -0.042 (interval -0.097 to 0.0); 0 tasks better, 3 worse, 33 the same. No action was taken because of it [measured].
- **The one planned futility look** (first 20 blocks, upper bound 0.0, not below 0) did not stop the test and is unchanged [measured].
- **Servers.** 22 blocks on the Strix and 15 on the 5080; plain and v3.1 shared a server in every block [measured].
- **Archive.** The run files were copied off the 5080 before it was powered down; counts and sizes were checked [measured].
