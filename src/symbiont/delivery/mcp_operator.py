"""Run a `symbiont` subcommand inside the MCP server and return what it printed.

The server is outside the harness sandbox, so the subcommand can write the data directory. stdout
is the JSON-RPC channel, so the capture also keeps stray prints out of it.
"""

import contextlib
import io
import time
from collections.abc import Callable

from symbiont.delivery.operator_tools import Operate, Outcome

# A tool call should return while the developer waits; mining carries on in the service.
MINE_WATCH_S = 45.0
Main = Callable[..., int]


class _WatchBudget:
    """A pause that gives up after `limit_s` in total.

    `repo mine` already ends its follow loop on KeyboardInterrupt with "mining keeps running in
    the service; watch it at <address>", which is the answer a tool call wants once its budget is
    spent, so the budget raises that instead of adding a second way to stop following.
    """

    def __init__(self, limit_s: float) -> None:
        """Start with nothing spent."""
        self._left = limit_s

    def __call__(self, seconds: float) -> None:
        """Sleep, or stop following when the budget is spent."""
        if self._left <= 0:
            raise KeyboardInterrupt
        time.sleep(seconds)
        self._left -= seconds


def operate_in_server(main: Main, watch_s: float = MINE_WATCH_S) -> Operate:
    """An `Operate` that runs `main(argv)` and returns what it printed.

    `main` is `symbiont.cli.main`; it is passed in so this module does not import the CLI.
    """

    def operate(argv: list[str]) -> Outcome:
        """Run the subcommand; an argparse exit is a failure with its message, never a crash."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(argv, mine_pause=_WatchBudget(watch_s))
            except SystemExit as exited:
                code = exited.code if isinstance(exited.code, int) else 1
        return Outcome(_joined(out.getvalue(), err.getvalue()), failed=code != 0)

    return operate


def _joined(printed: str, complained: str) -> str:
    """Both streams as one answer, so a failure's reason is never lost."""
    text = "\n".join(part.strip() for part in (printed, complained) if part.strip())
    return text or "(no output)"
