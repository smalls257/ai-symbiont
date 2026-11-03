"""The ledger lock makes two handles take turns on every platform (flock, or msvcrt on Windows).

Failure guarded against: a lock that silently does not lock, so two callers both pass the cap check
(Distributed Monolith) and overshoot the spend cap.
"""

import threading

from symbiont.egress.file_lock import exclusive_file_lock, locked_with_flock, locked_with_msvcrt


def test_a_second_handle_waits_until_the_first_releases(tmp_path):
    path = tmp_path / "ledger.lock"
    order: list[str] = []
    holding = threading.Event()
    release = threading.Event()

    def first():
        with path.open("w") as guard, exclusive_file_lock(guard):
            order.append("first in")
            holding.set()
            release.wait(5)
            order.append("first out")

    def second():
        with path.open("w") as guard, exclusive_file_lock(guard):
            order.append("second in")

    holder = threading.Thread(target=first)
    holder.start()
    assert holding.wait(5)
    waiter = threading.Thread(target=second)
    waiter.start()
    waiter.join(0.3)
    assert waiter.is_alive(), "the second handle got the lock while the first still held it"
    release.set()
    holder.join(5)
    waiter.join(5)

    assert order == ["first in", "first out", "second in"]


def test_the_lock_can_be_taken_again_after_release(tmp_path):
    with (tmp_path / "l").open("w") as guard:
        with exclusive_file_lock(guard):
            pass
        with exclusive_file_lock(guard):
            pass


class FakeMsvcrt:
    """Records `locking` calls and refuses the first, like a lock held by another process."""

    LK_NBLCK, LK_UNLCK = 2, 0

    def __init__(self):
        self.calls = []

    def locking(self, fd, mode, nbytes):
        self.calls.append((mode, nbytes))
        if len(self.calls) == 1:
            raise OSError("locked by another process")


def test_the_windows_lock_retries_until_free_and_unlocks_at_the_end(tmp_path):
    msvcrt = FakeMsvcrt()
    with (tmp_path / "l").open("w") as guard, locked_with_msvcrt(guard, msvcrt):
        assert msvcrt.calls == [(2, 1), (2, 1)]
    assert msvcrt.calls[-1] == (0, 1)


def test_the_posix_lock_takes_and_releases_an_exclusive_flock(tmp_path):
    seen = []

    class FakeFcntl:
        LOCK_EX, LOCK_UN = 2, 8

        @staticmethod
        def flock(guard, mode):
            seen.append(mode)

    with (tmp_path / "l").open("w") as guard, locked_with_flock(guard, FakeFcntl):
        assert seen == [2]
    assert seen == [2, 8]
