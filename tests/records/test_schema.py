import io
import json

import pytest

from symbiont.records.schema import (
    Kind,
    Provenance,
    Record,
    RecordFormatError,
    dump_jsonl,
    load_jsonl,
)

PUBLIC = Provenance(dataset="synthetic", license="CC-BY-4.0", spark_safe=True)


def make_record(step: int, raw: str = "ok", **overrides) -> Record:
    fields = dict(
        harness="openhands",
        project="tobymao/sqlglot",
        session_id="s1",
        step=step,
        kind=Kind.COMMAND,
        raw=raw,
        command="pytest tests/test_parser.py",
        exit_code=1,
        files=("sqlglot/parser.py",),
        provenance=PUBLIC,
    )
    return Record(**(fields | overrides))


def roundtrip(records: list[Record]) -> list[Record]:
    buf = io.StringIO()
    dump_jsonl(records, buf)
    buf.seek(0)
    return list(load_jsonl(buf))


def test_roundtrip_preserves_raw_bytes():
    awkward = 'naïve ✓ 日本語\r\nline two\n\ttab "quote" \\ backslash \x00 nul'
    big = ("SELECT * FROM t WHERE x = 'é';\n" * 2000)[:50_000]
    records = [
        make_record(0, raw=awkward, diff="--- a\n+++ b\n@@ -1 +1 @@\n-x\n+ÿ\n"),
        make_record(1, raw=big, kind=Kind.EDIT, command=None, exit_code=None),
    ]
    loaded = roundtrip(records)
    assert loaded == records
    assert loaded[0].raw.encode("utf-8") == awkward.encode("utf-8")
    assert len(loaded[1].raw) == 50_000


def test_optional_fields_default_to_unknown():
    record = Record(
        harness="openhands",
        project="p",
        session_id="s",
        step=0,
        kind=Kind.USER_TURN,
        raw="fix the bug",
        provenance=PUBLIC,
    )
    assert record.ts is None and record.command is None and record.exit_code is None
    assert record.files == () and record.diff is None and record.task_id is None


def test_provenance_required():
    with pytest.raises(TypeError):
        Provenance(dataset="synthetic", license="MIT")
    with pytest.raises(TypeError):
        Record(harness="h", project="p", session_id="s", step=0, kind=Kind.USER_TURN, raw="x")


def test_load_bad_line_names_line():
    buf = io.StringIO()
    dump_jsonl([make_record(0), make_record(1)], buf)
    buf.write('{"harness": "openhands", "step": \n')
    buf.seek(0)
    with pytest.raises(RecordFormatError) as err:
        list(load_jsonl(buf))
    assert err.value.line_no == 3


def test_load_line_missing_spark_safe_is_rejected_not_assumed_safe():
    line = json.loads(_dumped_line(make_record(0)))
    del line["provenance"]["spark_safe"]
    buf = io.StringIO(json.dumps(line) + "\n")
    with pytest.raises(RecordFormatError) as err:
        list(load_jsonl(buf))
    assert err.value.line_no == 1
    assert "spark_safe" in str(err.value)


def test_load_unknown_kind_names_line():
    line = json.loads(_dumped_line(make_record(0)))
    line["kind"] = "telepathy"
    buf = io.StringIO(json.dumps(line) + "\n")
    with pytest.raises(RecordFormatError) as err:
        list(load_jsonl(buf))
    assert err.value.line_no == 1


def _dumped_line(record: Record) -> str:
    buf = io.StringIO()
    dump_jsonl([record], buf)
    return buf.getvalue()


def test_tags_roundtrip_as_a_tuple():
    """Dataset labels such as SWE-chat's pushback mark survive the round trip."""
    record = make_record(0, tags=("correction",))
    assert roundtrip([record]) == [record]
    assert make_record(1).tags == ()


def test_line_written_before_tags_existed_still_loads():
    data = json.loads(_dumped_line(make_record(0)))
    del data["tags"]
    (loaded,) = load_jsonl(io.StringIO(json.dumps(data) + "\n"))
    assert loaded.tags == ()


def test_line_range_roundtrips_as_a_tuple():
    """A file view keeps which lines it showed, so paging is not re-reading."""
    record = make_record(0, kind=Kind.READ, line_range=(120, 160))
    assert roundtrip([record]) == [record]
    assert make_record(1).line_range is None


def test_line_written_before_line_range_existed_still_loads():
    data = json.loads(_dumped_line(make_record(0)))
    del data["line_range"]
    (loaded,) = load_jsonl(io.StringIO(json.dumps(data) + "\n"))
    assert loaded.line_range is None
