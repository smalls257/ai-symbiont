# Plug round 4, amendment 1 (2026-10-30): the nightly adapters' hashes

Claim tags: [measured], [established], [hypothesis]. This amendment adds ONLY the nightly adapter hashes, their count, the idle-repository list and this date, in `results/plug-r4-nightly-amendment-pins.json`, as the frozen prereg's amendment path allows. It changes nothing about design, selection, rule or data.

- 89 adapters were trained (one per scored repository) from the general judge on lessons from tasks created before each repository's earliest scored recurrence; the idle list is empty (every repository had earlier lessons) [measured].
- The training script wrote each adapter's scores as it finished. Those score files were moved aside unread (hash of the file list kept) before this amendment and are not used; the scores the decision reads are recomputed from the pinned adapters after this commit [established].
- The primary and the general-judge arm were scored before this amendment (`results/plug-r4-scored-primary.json`, `results/plug-r4-scored-general.json`); their numbers are unaffected [measured].
