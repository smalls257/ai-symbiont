"""META2's row labels, verbatim from prereg/2026-10-28-meta2.md (section "Rows"). No torch needed.

The results file carries one label per row so a reader cannot take a reference for a floor or
the in-domain ceiling for a candidate.
"""

import meta2_inputs as md

COUNTERS_LABEL = (
    "reference (a heads-up at every allowed step: threshold 0 was chosen on validation)"
)
PER_K = "reference (per-k refit, the dispatch's named reference)"
LABELS = {
    "warn never": "floor",
    "note at every allowed step": "floor",
    "counters": COUNTERS_LABEL,
    "logistic broad": "reference (the live warner)",
    "logistic own tasks": PER_K,
    "logistic broad + refit": PER_K,
}
for _name in md.NETWORKS:
    LABELS.update(
        {
            f"{_name} cold": "under test",
            f"{_name} MAML start": "under test",
            f"{_name} broad": "under test (the fine-tune's comparator)",
            f"{_name} broad + fine-tune": "under test",
            f"{_name} in-domain": "ceiling (uses future tasks; never a candidate)",
        }
    )
