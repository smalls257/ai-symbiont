"""The demo page's two contracts: dashboard/sample/demo-replay.json and demo-headlines.json.

Violation prevented: Paper Tiger. The demo is the claim on stage, so a sample that drifts
from its schema, a plain run that quietly receives notes, totals that disagree with the
steps, or a network that "decides" to speak would film a result nobody measured. The
schemas are checked with a small validator that refuses any keyword it does not know, so a
keyword added later is a failure, never a rule that is silently not checked.
"""

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.periphery  # reads the committed sample files

SAMPLE = Path(__file__).resolve().parents[2] / "dashboard" / "sample"
ANNOTATIONS = {"$schema", "$id", "title", "$comment", "$defs"}
TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _load(name: str) -> dict:
    return json.loads((SAMPLE / name).read_text())


def _is_type(value: object, name: str) -> bool:
    if isinstance(value, bool) and name in {"integer", "number"}:
        return False
    return isinstance(value, TYPES[name])


def _check_object(value: dict, schema: dict, root: dict, at: str) -> list[str]:
    found = [f"{at}: missing {key}" for key in schema.get("required", []) if key not in value]
    props = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        found += [f"{at}: unexpected key {key}" for key in value if key not in props]
    for key, sub in props.items():
        if key in value:
            found += violations(value[key], sub, root, f"{at}.{key}")
    return found


def _check_array(value: list, schema: dict, root: dict, at: str) -> list[str]:
    found = []
    if len(value) < schema.get("minItems", 0):
        found.append(f"{at}: fewer than {schema['minItems']} items")
    if len(value) > schema.get("maxItems", len(value)):
        found.append(f"{at}: more than {schema['maxItems']} items")
    for index, item in enumerate(value):
        found += violations(item, schema.get("items", {}), root, f"{at}[{index}]")
    return found


def _check_scalar(value: object, schema: dict, at: str) -> list[str]:
    found = []
    if "const" in schema and value != schema["const"]:
        found.append(f"{at}: {value!r} is not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{at}: {value!r} not in {schema['enum']}")
    if isinstance(value, (int, float)) and value < schema.get("minimum", value):
        found.append(f"{at}: below minimum")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        found.append(f"{at}: empty string")
    if isinstance(value, str) and "pattern" in schema and not re.match(schema["pattern"], value):
        found.append(f"{at}: does not match {schema['pattern']}")
    return found


def violations(value: object, schema: dict, root: dict, at: str = "$") -> list[str]:
    """Every way `value` breaks `schema` (the subset of draft 2020-12 the demo uses)."""
    if "$ref" in schema:
        return violations(value, root["$defs"][schema["$ref"].split("/")[-1]], root, at)
    if "oneOf" in schema:
        passing = [sub for sub in schema["oneOf"] if not violations(value, sub, root, at)]
        return [] if len(passing) == 1 else [f"{at}: matches {len(passing)} oneOf branches"]
    names = schema.get("type")
    names = [names] if isinstance(names, str) else names
    if names and not any(_is_type(value, name) for name in names):
        return [f"{at}: {type(value).__name__} is not {names}"]
    if isinstance(value, dict):
        return _check_object(value, schema, root, at)
    if isinstance(value, list):
        return _check_array(value, schema, root, at)
    return _check_scalar(value, schema, at)


KNOWN = ANNOTATIONS | {
    "type", "const", "enum", "required", "properties", "additionalProperties", "items",
    "minItems", "maxItems", "minimum", "minLength", "pattern", "oneOf", "$ref",
}  # fmt: skip


def _keywords(schema: object) -> set[str]:
    if isinstance(schema, list):
        return set().union(*(_keywords(item) for item in schema)) if schema else set()
    if not isinstance(schema, dict):
        return set()
    found = set(schema)
    for key, sub in schema.items():
        if key in {"properties", "$defs"}:
            found |= set().union(*(_keywords(s) for s in sub.values()))
        elif key in {"items", "oneOf"}:
            found |= _keywords(sub)
    return found


@pytest.mark.parametrize("name", ["demo-replay", "demo-headlines"])
def test_schema_uses_only_keywords_the_validator_checks(name):
    assert _keywords(_load(f"{name}.schema.json")) <= KNOWN


@pytest.mark.parametrize("name", ["demo-replay", "demo-headlines"])
def test_shipped_sample_matches_its_schema(name):
    schema = _load(f"{name}.schema.json")
    assert violations(_load(f"{name}.json"), schema, schema) == []


def _replay_violations(doc: dict) -> list[str]:
    schema = _load("demo-replay.schema.json")
    return violations(doc, schema, schema)


def test_network_cannot_carry_a_speak_decision():
    doc = _load("demo-replay.json")
    picker = doc["runs"][1]["steps"][0]["picker"]
    picker["speak"] = "speak"
    assert any(".steps[0].picker: matches 0 oneOf" in v for v in _replay_violations(doc))


def test_classifier_decision_must_be_labelled_logistic_classifier():
    doc = _load("demo-replay.json")
    doc["runs"][1]["steps"][1]["classifier"]["who"] = "our network"
    assert _replay_violations(doc)


def test_note_without_a_known_source_is_refused():
    doc = _load("demo-replay.json")
    doc["runs"][1]["steps"][1]["note"]["source"] = "fly brain"
    assert _replay_violations(doc)


def _run(doc: dict, run_id: str) -> dict:
    return next(run for run in doc["runs"] if run["id"] == run_id)


def test_plain_run_receives_no_notes_and_no_decisions():
    plain = _run(_load("demo-replay.json"), "plain")
    assert all(s["note"] is None and s["classifier"] is None for s in plain["steps"])
    assert all(s["picker"] is None for s in plain["steps"])
    assert plain["adapter"] is None


@pytest.mark.parametrize("run_id", ["plain", "personal"])
def test_totals_are_the_sums_of_the_steps(run_id):
    run = _run(_load("demo-replay.json"), run_id)
    steps, totals = run["steps"], run["totals"]
    assert totals["steps"] == len(steps)
    assert [s["step"] for s in steps] == list(range(1, len(steps) + 1))
    for key in ("tokens_in", "tokens_out"):
        assert totals[key] == sum(s[key] for s in steps)
    assert totals["wall_s"] == pytest.approx(sum(s["wall_s"] for s in steps), abs=0.05)
    assert totals["repeated_mistakes"] == sum(s["mistake_tag"] == "repeated" for s in steps)
    assert totals["new_mistakes"] == sum(s["mistake_tag"] == "new" for s in steps)
    assert totals["wasted_steps"] == sum(s["wasted"] for s in steps)
    assert totals["notes"] == sum(s["note"] is not None for s in steps)


def test_synthetic_replay_is_tagged_hypothesis_and_says_so():
    doc = _load("demo-replay.json")
    assert doc["status"] == "hypothesis"
    assert all(run["status"] == "hypothesis" for run in doc["runs"])
    assert "synthetic" in doc["source"]


def test_every_fly_row_has_counters_directly_beside_it():
    for headline in _load("demo-headlines.json")["headlines"]:
        labels = [row["label"] for row in headline["rows"]]
        for index, label in enumerate(labels):
            if label.startswith("fly"):
                assert "counters" in labels[max(0, index - 1) : index + 2], headline["id"]
