"""The published AIDev document: counts, rates, ids and labels only (QG-SEC-04 shapes).

A "changed later" rate for flagged hunks means nothing without the unflagged rate beside it under
the same cut, so every flagged row is printed with its reference rows, per agent, with the censored
and unknown units that the rate leaves out. Pure: counts in, a json-ready dict out.
"""

from collections import Counter

SOURCE = "AIDev v4 (HF hao-li/AIDev, CC-BY-4.0, Hao Li et al., arXiv 2507.15003)"
ROLE = {"human": "under_test", "bot": "reference", "none": "reference"}
CUTS = {
    "all": "judged after the flag, or after its own commit if unflagged",
    "first_review": "units live at the first human review, judged after it",
}


def rate_row(cut: str, agent: str, flag: str, counts: dict) -> dict:
    """One scoreboard row: how often units of this arm changed later."""
    changed, survived = counts.get("changed") or 0, counts.get("survived") or 0
    judged = changed + survived
    return {
        "cut": cut,
        "agent": agent,
        "arm": f"{flag}_flagged" if flag != "none" else "unflagged",
        "role": ROLE[flag],
        "changed": changed,
        "survived": survived,
        "censored": counts.get("censored") or 0,
        "unknown": counts.get("unknown") or 0,
        "changed_rate": round(changed / judged, 4) if judged else None,
    }


def signal_rows(signal: dict) -> list[dict]:
    """Rows per cut, agent and arm, plus an all-agents row per cut and arm."""
    rows = []
    for cut, by_agent in signal.items():
        pooled: dict[str, Counter[str]] = {}
        for agent in sorted(by_agent):
            for flag, counts in sorted(by_agent[agent].items()):
                rows.append(rate_row(cut, agent, flag, counts))
                pooled.setdefault(flag, Counter()).update({k: v for k, v in counts.items() if v})
        rows.extend(rate_row(cut, "all_agents", flag, c) for flag, c in sorted(pooled.items()))
    return rows


def lifts(rows: list[dict]) -> dict:
    """Human-flagged rate over unflagged rate, per cut and agent."""
    by_key = {(r["cut"], r["agent"], r["arm"]): r["changed_rate"] for r in rows}
    found = {}
    for cut, agent, arm in by_key:
        if arm != "human_flagged":
            continue
        flagged, base = by_key[(cut, agent, arm)], by_key.get((cut, agent, "unflagged"))
        if flagged is not None and base:
            found[f"{cut}:{agent}"] = round(flagged / base, 3)
    return found


def results_document(tally, found: list, kept: list, training: dict) -> dict:
    """The whole results file."""
    rows = signal_rows(tally.signal)
    return {
        "source": SOURCE,
        "status": "exploratory, no prereg; counts and labels only",
        "rule": (
            "Unit: one added hunk, followed through later commits of its PR in pr_commits row "
            "order; changed when a later commit removes or inserts inside its lines; flagged when "
            "an inline comment's anchor line is in its live lines."
        ),
        "cuts": CUTS,
        "commit_order_votes": dict(sorted(tally.order.items())),
        "anchoring_by_agent": {
            a: dict(sorted(c.items())) for a, c in sorted(tally.anchoring.items())
        },
        "unreadable": dict(tally.unreadable),
        "rows": rows,
        "lift_human_over_unflagged": lifts(rows),
        "miner_content_rule_on_human_flags": dict(sorted(tally.miner_agreement.items())),
        "lessons": {
            "label": "kinds by keyword rules, precision not checked by reading",
            "found_by_kind": dict(Counter(item.kind.value for item in found)),
            "kept_by_kind": dict(Counter(item.kind.value for item in kept)),
            "kept_by_agent": dict(Counter(item.agent for item in kept)),
            "found": len(found),
            "kept": len(kept),
            "repos": len({item.repo for item in kept}),
            "dropped": dict(sorted(tally.dropped.items())),
        },
        "training": training,
        "notes": (
            "Patch and comment text stay local under each source repository's license; no text "
            "from them appears in lessons, rows or this file."
        ),
    }
