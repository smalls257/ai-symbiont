"""check_naming: every rule fires on its bad source and stays quiet on the near miss."""

from datetime import date

import pytest

from gate_loader import load_gate

naming = load_gate("check_naming")
PATH = "src/symbiont/core/thing.py"


def errors(source: str, waived: frozenset[str] = frozenset()) -> list[str]:
    return naming.check_source(source, PATH, set(waived))[0]


def warnings(source: str) -> list[str]:
    return naming.check_source(source, PATH, set())[1]


@pytest.mark.parametrize(
    "name",
    [
        "handle_event",
        "process_rows",
        "manage_state",
        "do_work",
        "run_it",
        "load_data",
        "get_info",
        "StuffBag",
        "SessionManager",
        "RequestHandler",
        "RowProcessor",
        "FileHelper",
        "string_utils",
        "misc_things",
        "Util",
        "helpers",
    ],
)
def test_vague_names_fire(name):
    assert errors(f"def {name}(): ...\n"), name


@pytest.mark.parametrize(
    "name",
    [
        "recall_pain_point",
        "dataset_rows",
        "metadata_for",
        "processed_rows_count",
        "undo",
        "window",
        "handled",
        "DataclassView",
        "mine_session",
    ],
)
def test_words_that_merely_contain_a_vague_substring_do_not_fire(name):
    # whole-word match only: "dataset", "metadata", "undo", "handled" are different words
    assert errors(f"def {name}(): ...\n") == []


def test_a_vague_class_and_a_vague_module_fire():
    assert errors("class SessionManager: ...\n")
    found, _ = naming.check_source("x = 1\n", "src/symbiont/core/utils.py", set())
    assert any("utils" in e for e in found)


def test_dunder_init_module_is_fine():
    assert naming.check_source("x = 1\n", "src/symbiont/core/__init__.py", set())[0] == []


def test_single_letter_names_fire_outside_loops_and_comprehensions():
    assert errors("def f(n):\n    return n\n")
    assert errors("def build():\n    s = 1\n    return s\n")
    assert errors(
        "def build():\n    try:\n        pass\n    except ValueError as e:\n        raise\n"
    )


def test_loop_targets_x_y_and_underscore_are_allowed():
    ok = (
        "def build(rows, x, y):\n"
        "    total = [r for r in rows]\n"
        "    for i in range(3):\n"
        "        pass\n"
        "    for _ in rows:\n"
        "        pass\n"
        "    return total, x + y\n"
    )
    assert errors(ok) == []


def test_two_bool_parameters_fire_one_does_not():
    assert errors("def f(rows, strict: bool, verbose: bool): ...\n")
    assert errors("def f(rows, *, strict=False, verbose=True): ...\n")
    assert errors("def f(rows, strict: bool, verbose: int): ...\n") == []
    assert errors("def f(rows, *, strict: bool = False): ...\n") == []


def test_flag_like_positional_parameters_warn_but_keyword_only_do_not():
    assert warnings("def f(rows, is_ready, use_cache): ...\n")
    assert warnings("def f(rows, *, is_ready, use_cache): ...\n") == []
    assert errors("def f(rows, is_ready, use_cache): ...\n") == []


def test_waiver_silences_exactly_one_name():
    source = "def handle_event(): ...\ndef process_rows(): ...\n"
    found = errors(source, frozenset({f"{PATH}:handle_event"}))
    assert len(found) == 1 and "process_rows" in found[0]


def test_waiver_without_a_future_expiry_is_refused(tmp_path):
    file = tmp_path / "w.txt"
    today = date(2026, 10, 27)
    file.write_text("# header\nsrc/a.py:handle_it\n")
    with pytest.raises(naming.WaiverError):
        naming.read_waivers(file, today)
    file.write_text("src/a.py:handle_it  # me, legacy, expires 2026-01-01\n")
    with pytest.raises(naming.WaiverError):
        naming.read_waivers(file, today)
    file.write_text("src/a.py:handle_it  # me, legacy, expires 2026-12-31\n")
    assert naming.read_waivers(file, today) == {"src/a.py:handle_it"}


@pytest.mark.parametrize("base", ["BaseHTTPRequestHandler", "http.server.SimpleHTTPRequestHandler"])
def test_http_verb_method_of_a_stdlib_request_handler_is_exempt(base):
    assert errors(f"class Routes({base}):\n    def do_POST(self): ...\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "class Routes(BaseHTTPRequestHandler):\n    def do_stuff(self): ...\n",
        "class Routes(BaseHTTPRequestHandler):\n    def do_post(self): ...\n",
        "class Other:\n    def do_POST(self): ...\n",
        "class Other(object):\n    def do_POST(self): ...\n",
        "def do_POST(): ...\n",
    ],
)
def test_do_names_outside_the_stdlib_http_contract_still_fire(source):
    assert any("vague word 'do'" in message for message in errors(source))
