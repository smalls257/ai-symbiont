"""Plug round 2's scored run: guard, plan check, no-lesson items, and the frozen decision rule.

Usage: uv run python scripts/routea/plug_r2_score.py check --pool P --habit-rows H --aidev-lessons L
Usage:   --prereg prereg/2026-10-29-plug-situations.md --work W
Usage: uv run python scripts/routea/plug_r2_score.py bare --work W  |  score --work W --out F

`check` refuses unless the inputs match their pins and the code at HEAD is the freeze commit's.
`score` prints every row and applies H1 and H2; a missing answer file raises.
"""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug import InputHashMismatchError, pinned_code_commit, pool_index_sha, sha256_of  # noqa: E402
from plug_r2_select import better, gate, per_repo  # noqa: E402
from plug_situation import item_from, item_record  # noqa: E402
from questions import SYSTEM  # noqa: E402
from warm_start import _jsonl, _read_jsonl, answerer_provenance, paired_gain  # noqa: E402

from symbiont.eval.prereg_git import run_provenance  # noqa: E402

PREREG_NAME = "2026-10-29-plug-situations.md"
PINNED = {
    "pool_index_sha256": "a14f22f0158a2ac568f84ffdbbbafaa01059cf22abebc5f4370679623cd258ff",
    "habit_rows_sha256": "fa863cb3f13bf66907a16d076cf4d2ffab705272ef785d16ea93c19a271c06ea",
}


class PlanMismatchError(ValueError):
    """The plan differs from the prereg's table; names the difference."""


SCORED = {  # the prereg's table: scored repo -> distinct lessons
    "AzureAD/microsoft-authentication-library-for-python": 4,
    "BAMWelDX/weldx": 3,
    "DOV-Vlaanderen/pydov": 3,
    "Materials-Consortia/optimade-python-tools": 3,
    "PyCQA/flake8-bugbear": 3,
    "TheFriendlyCoder/friendlypins": 3,
    "andialbrecht/sqlparse": 3,
    "awdeorio/mailmerge": 6,
    "bids-standard/pybids": 4,
    "codalab/codalab-worksheets": 6,
    "datalad/datalad": 7,
    "devopshq/artifactory": 4,
    "dwavesystems/dwave-cloud-client": 4,
    "dwavesystems/dwave-system": 6,
    "fjosw/pyerrors": 4,
    "graphql-python/graphene-django": 3,
    "hgrecco/pint-pandas": 5,
    "keras-team/keras-nlp": 4,
    "lincc-frameworks/nested-pandas": 4,
    "matchms/matchms": 3,
    "mhostetter/galois": 4,
    "mikedh/trimesh": 3,
    "missionpinball/mpf": 5,
    "mwouts/jupytext": 5,
    "narwhals-dev/narwhals": 4,
    "ncclient/ncclient": 6,
    "nltk/nltk": 3,
    "nosarthur/gita": 4,
    "omni-us/jsonargparse": 4,
    "optuna/optuna": 3,
    "pre-commit/pre-commit-hooks": 3,
    "psf/black": 4,
    "pypa/setuptools_scm": 5,
    "pypa/virtualenv": 4,
    "python-cmd2/cmd2": 3,
    "sqlfluff/sqlfluff": 6,
    "sunpy/sunpy": 4,
    "tophat/syrupy": 3,
    "yt-dlp/yt-dlp": 4,
    "zalando-stups/senza": 6,
}
META_JOIN = {
    "RockefellerArchiveCenter/DACSspace": 6,
    "algorand/pyteal": 3,
    "hgrecco/pint": 5,
    "macbre/sql-metadata": 3,
    "microsoft/electionguard-python": 3,
    "miurahr/aqtinstall": 4,
    "nteract/papermill": 4,
    "reata/sqllineage": 4,
    "reframe-hpc/reframe": 3,
    "scverse/scanpy": 3,
    "spdx/tools-python": 3,
}


def check_plan(plan: dict) -> None:
    """Raise PlanMismatchError unless the plan's scored and meta-joining repos are the prereg's."""
    for key, expected in (("scored", SCORED), ("meta_join", META_JOIN)):
        if plan[key] != expected:
            raise PlanMismatchError(f"plan's {key} differs from the prereg's table")


SCORED_ROWS = {  # row: (answers subdir, label)
    "floor_plain": ("top5", "floor"),
    "floor_plain_bare": ("bare", "floor"),
    "reader": ("top5", "under_test"),
    "reader_bare": ("bare", "floor"),
    "ranker": ("top5", "reference"),
}


def check(args: argparse.Namespace) -> dict:
    """Inputs against their pins, the frozen prereg and the code commit; refuses any mismatch."""
    found = {
        "pool_index_sha256": pool_index_sha(args.pool),
        "habit_rows_sha256": sha256_of(args.habit_rows),
    }
    for name, expected in PINNED.items():
        if found[name] != expected:
            raise InputHashMismatchError(f"{name} is {found[name]}, the prereg pins {expected}")
    check_plan(json.loads((args.work / "plan.json").read_text()))
    label = run_provenance(scored=True, prereg=args.prereg, expects=PREREG_NAME)
    code = pinned_code_commit(HERE.parents[1], label["freeze_commit"])
    provenance = {
        **label,
        **found,
        "code_commit": code,
        "aidev_lessons_sha256": sha256_of(args.aidev_lessons),
    }
    (args.work / "provenance.json").write_text(json.dumps(provenance, indent=1, sort_keys=True))
    return provenance


def bare_records(records: list[dict]) -> list[dict]:
    """The same items with no lessons shown: the situation alone, under the memory system."""
    found = []
    for record in records:
        item = replace(item_from(record), prompt_lessons=(), excused=())
        found.append(item_record(item) | {"context": SYSTEM, "repo": record["repo"]})
    return found


def claim(h1: dict, h2: dict, means: dict[str, dict]) -> str:
    """The report's sentence, fixed by the prereg's wording."""
    if h1["decision"] == "better" and h2["passes"]:
        return (
            f"picks the applicable lesson in {means['reader']['pick']:.2f} of situations on 40 "
            f"unseen repos, against {means['floor_plain']['pick']:.2f} for the plain model with "
            f"the same prompt, and stays silent in {means['reader']['silence']:.2f} of situations "
            "with no applicable lesson"
        )
    sentence = (
        "the trained reader did not measurably beat the plain model "
        f"(gain {h1['mean_gain']:+.2f}, interval {h1['ci95_low']:+.2f} to {h1['ci95_high']:+.2f})"
    )
    if h1["decision"] == "better":
        sentence = "picks more and fails the abstention gate"
    return sentence


def score(work: Path, selected: str) -> dict:
    """Every row's rates and the decisions. If no variant passed validation (`selected` is the
    floor), the reader rows are absent and the floor is reported."""
    rows = {
        r: v for r, v in SCORED_ROWS.items() if selected != "floor" or not r.startswith("reader")
    }
    cells = {row: per_repo(work / sub, row) for row, (sub, _) in rows.items()}
    repos = sorted(cells["floor_plain"])
    measures = ("pick", "useful", "silence", "wrong_pick")
    means = {
        row: {m: paired_gain([c[m] for c in cells[row].values()])["mean_gain"] for m in measures}
        for row in cells
    }
    document = {
        **json.loads((work / "provenance.json").read_text()),
        **answerer_provenance(work),
        "selected": selected,
        "rows": [{"arm": row, "role": label, **means[row]} for row, (_, label) in rows.items()],
        "per_repo_rows": [{"arm": row, "repo": r, **cells[row][r]} for row in cells for r in repos],
    }
    if selected == "floor":
        return {
            **document,
            "result": "no variant passed validation; the plain model and ranker alone are reported",
        }
    return {**document, **decisions(cells, repos, means)}


def decisions(cells: dict, repos: list[str], means: dict) -> dict:
    """H1, H2, the ranker-alone secondary and the claim sentence."""
    h1 = better([cells["reader"][r]["pick"] - cells["floor_plain"][r]["pick"] for r in repos])
    h2 = gate(cells["reader"])
    versus_ranker = better([cells["reader"][r]["pick"] - cells["ranker"][r]["pick"] for r in repos])
    adds = (
        ""
        if versus_ranker["decision"] == "better"
        else "the reader adds nothing the ranker's first guess did not"
    )
    return {
        "h1_reader_minus_floor_pick": h1,
        "h2_abstention_gate": h2,
        "secondary_reader_minus_ranker_pick": {**versus_ranker, "label": adds},
        "result": claim(h1, h2, means),
    }


def main() -> None:
    """Run one stage."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("check", "bare", "score"))
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--habit-rows", type=Path)
    parser.add_argument("--aidev-lessons", type=Path)
    parser.add_argument("--prereg")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selected", help="the selection amendment's variant, or floor")
    args = parser.parse_args()
    if args.stage == "check":
        print(json.dumps(check(args), indent=1))
    elif args.stage == "bare":
        records = _read_jsonl(args.work / "top5" / "items.jsonl")
        _jsonl(args.work / "bare" / "items.jsonl", bare_records(records))
        print(json.dumps({"items": len(records)}))
    else:
        text = json.dumps(score(args.work, args.selected), indent=1, sort_keys=True)
        args.out.write_text(text + "\n")
        print(text)


if __name__ == "__main__":
    main()
