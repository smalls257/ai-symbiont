"""Hook input and MCP output are UTF-8 with LF on every platform, whatever the console code page.

Failure guarded against: a non-ASCII prompt mined as mojibake on Windows (Silent Fallback: wrong
text, no error), and CRLF-terminated JSON-RPC lines.
"""

import io
import subprocess
import sys

import pytest

from symbiont.delivery import stdio

pytestmark = pytest.mark.periphery


def test_a_replaced_stream_is_left_alone(monkeypatch):
    fake = io.StringIO("x")
    monkeypatch.setattr(sys, "stdin", fake)
    stdio.use_utf8_lf_stdio()
    assert sys.stdin is fake


def test_a_child_with_a_legacy_code_page_still_reads_and_writes_utf8_with_lf():
    code = (
        "import sys; from symbiont.delivery.stdio import use_utf8_lf_stdio as u; u(); "
        "t = sys.stdin.read(); sys.stdout.write(t + '\\n')"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        input="caf\u00e9 \u2014 \u2713".encode(),
        capture_output=True,
        env={"PYTHONIOENCODING": "cp1252", "PATH": "", "SYSTEMROOT": "C:\\Windows"},
        check=True,
    )
    assert done.stdout == "caf\u00e9 \u2014 \u2713\n".encode()
