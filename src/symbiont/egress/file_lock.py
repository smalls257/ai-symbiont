"""An exclusive, cross-process lock on an open file, per operating system.

The spend ledger's cap check and reservation must be one step across every process. `fcntl` is
POSIX-only and importing it on Windows breaks the whole egress package, so the choice lives here.
"""

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any

# Windows `msvcrt.locking` gives up after ~10 s of its own retries; we keep waiting, as flock does.
_RETRY_S = 0.05


@contextmanager
def exclusive_file_lock(guard: IO[Any]) -> Iterator[None]:
    """Hold an exclusive lock on `guard` (an open file) until the block ends; waits for others."""
    if sys.platform == "win32":
        with _windows_lock(guard):
            yield
    else:
        with _posix_lock(guard):
            yield


@contextmanager
def _posix_lock(guard: IO[Any]) -> Iterator[None]:
    import fcntl

    fcntl.flock(guard, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(guard, fcntl.LOCK_UN)


@contextmanager
def _windows_lock(guard: IO[Any]) -> Iterator[None]:
    import msvcrt

    # One byte at offset 0 is the whole lock; locking past the end of an empty file is allowed.
    guard.seek(0)
    while True:
        try:
            msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            time.sleep(_RETRY_S)
    try:
        yield
    finally:
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
