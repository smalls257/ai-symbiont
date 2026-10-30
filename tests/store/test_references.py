import pytest

from symbiont.store.references import build_references

pytestmark = pytest.mark.periphery


def _write(root, path, text=""):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def test_build_references_finds_python_imports(tmp_path):
    _write(tmp_path, "sqlglot/__init__.py", "from sqlglot.parser import Parser\n")
    _write(tmp_path, "sqlglot/parser.py", "from sqlglot import tokens\n")
    _write(tmp_path, "sqlglot/tokens.py")
    _write(tmp_path, "sqlglot/dialects/__init__.py")
    _write(tmp_path, "sqlglot/dialects/dialect.py", "import sqlglot.parser as p\n")
    _write(tmp_path, "sqlglot/dialects/duckdb.py", "from sqlglot.dialects.dialect import Dialect\n")
    _write(tmp_path, "sqlglot/dialects/hive.py", "from .dialect import Dialect\n")
    _write(tmp_path, "tests/dialects/test_duckdb.py", "from sqlglot import exp\n")

    refs = build_references(tmp_path)

    assert refs["sqlglot/dialects/dialect.py"] == frozenset(
        {"sqlglot/dialects/duckdb.py", "sqlglot/dialects/hive.py"}
    )
    assert refs["sqlglot/tokens.py"] == frozenset({"sqlglot/parser.py"})
    assert "sqlglot/dialects/dialect.py" in refs["sqlglot/parser.py"]
    # Test files name their subject by convention: test_duckdb.py tests duckdb.py.
    assert "tests/dialects/test_duckdb.py" in refs["sqlglot/dialects/duckdb.py"]
    assert "tests/dialects/test_duckdb.py" in refs["sqlglot/__init__.py"]


def test_unparseable_file_is_named(tmp_path):
    _write(tmp_path, "sqlglot/broken.py", "def (:\n")
    with pytest.raises(SyntaxError, match="broken.py"):
        build_references(tmp_path)
