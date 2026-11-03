# PREREG D3 oracle addendum — dated 2026-11-03, written before any oracle run

**Label (use everywhere): "oracle: lesson text set by hand to the maintainer's exact words". A reference row, not a product claim.**
Question: do the reviewer's exact words, instead of Spark's paraphrase, change what Spark writes on B (#7433)?
- Build: main `3177282ba18f444a3895a337507605b9c0296d95` (same as D3 v2), install `pair/symbiont-src-3177282`, sha asserted before each run.
- Store: copy of the frozen `pair/data-snapshot-d3` (a906b570ed7ae76b...). With the product's own commands, not raw SQL: the Spark-written rule lesson `w-ae12b6993418` is dismissed with `symbiont forget --lesson w-ae12b6993418`, and one lesson is added through the same service call Spark's tool uses (`lessons/add`, i.e. `symbiont_add_lessons`) with the maintainer's words VERBATIM from PR #7396's review comment (id 2994938521, georgesittas): "We don't need to copy here. This is taken care of in the top-level `generate` method of the generator." Text = `Maintainer review on PR #7396: "<that sentence, unchanged>"`. Kind `rule`, files `sqlglot/generators/duckdb.py`, applies terms/areas copied from the Spark lesson (copy, properties, generate / generator, duckdb generation), source_label "from PR #7396 review", source_url the PR's https address. (`symbiont context add` was not used because it appends the human words after Spark's paraphrase instead of replacing it.) All other 9 lessons untouched.
- Replay gate (zero Spark) on the oracle store with the two viability runs; stop if the oracle lesson is not delivered.
- Runs: ON x4 fresh (`D3o-on-1..4`), same B, prompt, tests, model, harness and checker as D3 v2. Compared with the D3 v2 OFF runs (`D3v2-off-1..4`: 0, 5, 0, 6 added `.copy()` lines) on v2's primary: violating runs (>=1 added `.copy(` line), plus counts. No new OFF runs.
- Read as: if oracle ON violates in 0-1 of 4 versus OFF 2 of 4, exact words may matter; N=4 and OFF swinging 0-6 means any difference is a pilot signal. No rescue runs. Cap: D3 total $11 (about $5.3 spent). [hypothesis]

---
Committed copy, added after the runs. The only changes from the frozen file (sha256 c7b0260b880b89a25e28ab87e7e450507508f04e632dacff6689b7139272709e) are the claim tag appended to the line(s) the claim-tag gate flagged, and this note; no rule, arm, task, threshold or number differs.
