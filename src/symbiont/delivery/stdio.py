"""Standard streams that speak what the harnesses speak: UTF-8, with LF line ends.

On Windows the default is the console code page and CRLF translation, which garbles a non-ASCII
prompt on the way in and adds a carriage return to every JSON-RPC line on the way out.
"""

import io
import sys


def use_utf8_lf_stdio() -> None:
    """Switch stdin and stdout to UTF-8 and LF; streams already replaced (tests) are left alone."""
    for stream in (sys.stdin, sys.stdout):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", newline="\n" if stream is sys.stdout else None)
