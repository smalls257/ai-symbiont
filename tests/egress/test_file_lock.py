"""The ledger lock makes two handles take turns on every platform (flock, or msvcrt on Windows).

Failure guarded against: a lock that silently does not lock, so two callers both pass the cap check
(Distributed Monolith) and overshoot the spend cap.
"""

import threading

from symbiont.egress.file_lock import exclusive_file_lock


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
