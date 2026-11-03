"""An exclusive, cross-process lock on an open file, per operating system.

The spend ledger's cap check and reservation must be one step across every process. `fcntl` is
POSIX-only and importing it on Windows breaks the whole egress package, so the choice lives here.
"""

import sys
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import IO, Any

# Windows `msvcrt.locking` gives up after ~10 s of its own retries; we keep waiting, as flock does.
_RETRY_S = 0.05


def exclusive_file_lock(guard: IO[Any]) -> AbstractContextManager[None]:
    """Hold an exclusive lock on `guard` (an open file) until the block ends; waits for others."""
    if sys.platform == "win32":
        import msvcrt

        return locked_with_msvcrt(guard, msvcrt)
    import fcntl

    return locked_with_flock(guard, fcntl)


@contextmanager
def locked_with_flock(guard: IO[Any], fcntl_module: Any) -> Iterator[None]:
    """The POSIX lock; the module is passed in so each implementation is tested on every OS."""
    fcntl_module.flock(guard, fcntl_module.LOCK_EX)
    try:
        yield
    finally:
        fcntl_module.flock(guard, fcntl_module.LOCK_UN)


@contextmanager
def locked_with_msvcrt(guard: IO[Any], msvcrt_module: Any) -> Iterator[None]:
    """The Windows lock: one byte at offset 0, retried until free (locking past EOF is allowed)."""
    guard.seek(0)
    while True:
        try:
            msvcrt_module.locking(guard.fileno(), msvcrt_module.LK_NBLCK, 1)
            break
        except OSError:
            time.sleep(_RETRY_S)
    try:
        yield
    finally:
        guard.seek(0)
        msvcrt_module.locking(guard.fileno(), msvcrt_module.LK_UNLCK, 1)
