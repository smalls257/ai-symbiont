from pathlib import Path


class ReadError(ValueError):
    """A history file holds something a reader cannot parse.

    Raised, never skipped: a silently dropped session would quietly remove the
    very mistakes the miner exists to find. Callers (the setup wizard) name the
    file and line and ask the developer what to do.
    """

    def __init__(self, path: Path, line_no: int, reason: str):
        super().__init__(f"{path}:{line_no}: {reason}")
        self.path = path
        self.line_no = line_no
        self.reason = reason
