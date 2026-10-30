"""The markdown results table: the fly row never renders without its references.

Violation prevented: **Paper Tiger**. A fly number alone cannot say whether it
beats the plain counters, so `render_table` refuses to draw without the
counters and similarity rows beside it. Pure: scores in, text out.
"""

from collections.abc import Mapping, Sequence

from symbiont.eval.offline import OfflineScores

ROW_LABELS = {
    "counters": "reference",
    "similarity": "reference",
    "fly": "mushroom body, fly's published counts, random wiring (under test)",
}
FLAG_COLUMN = "balanced accuracy (AUROC of the binary flag)"


class MissingRowError(ValueError):
    """The table was asked for without all of the counters, similarity and fly rows."""

    def __init__(self, missing: Sequence[str]):
        self.missing = tuple(missing)
        super().__init__(
            "the table needs the counters, similarity and fly rows together; "
            f"missing: {', '.join(missing)}"
        )


FLY_SEED_LABEL = "mushroom body, wiring seed {seed} (threshold calibrated on train for this seed)"
FLY_AVERAGE_LABEL = (
    "mushroom body, fly's published counts, random wiring, "
    "seed-averaged over wiring seeds 0-2 (under test; the row the G6 rule uses)"
)
FOOTNOTE = (
    "[1] Mushroom recall@3 uses the word pre-filter: it re-ranks similarity's own "
    "word-sharing candidates, so its recall is not the unfiltered design."
)


def render_table(
    rows: Mapping[str, OfflineScores], *, fly_seeds: Mapping[int, OfflineScores] | None = None
) -> str:
    """Markdown table; refuses without all three rows.

    A fly number alone cannot say whether it beats the plain counters. The fly
    row is either one run (`rows["fly"]`) or, with `fly_seeds`, the
    seed-averaged row the G6 rule judges followed by each wiring seed, so a
    lucky wiring cannot hide.
    """
    if fly_seeds is not None and "fly" in rows:
        raise ValueError("give either a fly row or fly_seeds, not both")
    have = set(rows) | ({"fly"} if fly_seeds else set())
    missing = [name for name in ROW_LABELS if name not in have]
    if missing:
        raise MissingRowError(missing)
    lines = [f"| row | label | {FLAG_COLUMN} | recall@3 | steps |", "|---|---|---|---|---|"]
    for name, label in ROW_LABELS.items():
        if name == "fly" and fly_seeds:
            lines.append(_seed_average_line(fly_seeds))
            lines.extend(
                _line(f"fly seed {k}", FLY_SEED_LABEL.format(seed=k), fly_seeds[k], note=True)
                for k in sorted(fly_seeds)
            )
        else:
            lines.append(_line(name, label, rows[name], note=name == "fly"))
    return "\n".join([*lines, "", FOOTNOTE])


def _recall_text(recall: float | None, *, note: bool) -> str:
    text = "n/a" if recall is None else f"{recall:.3f}"
    return text + (" [1]" if note else "")


def _line(name: str, label: str, scores: OfflineScores, *, note: bool) -> str:
    recall = _recall_text(scores.recall_at_3, note=note)
    return f"| {name} | {label} | {scores.auroc:.3f} | {recall} | {scores.n_steps} |"


def _seed_average_line(seeds: Mapping[int, OfflineScores]) -> str:
    runs = list(seeds.values())
    recalls = [r.recall_at_3 for r in runs if r.recall_at_3 is not None]
    recall = sum(recalls) / len(recalls) if recalls else None
    auroc_mean = sum(r.auroc for r in runs) / len(runs)
    recall_text = _recall_text(recall, note=True)
    return f"| fly | {FLY_AVERAGE_LABEL} | {auroc_mean:.3f} | {recall_text} | {runs[0].n_steps} |"
