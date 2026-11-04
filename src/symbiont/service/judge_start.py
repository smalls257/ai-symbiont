"""How a repository's judge server is started: the facts a nightly record keeps for it.

After a reboot the judge server is gone while the nightly record still says "trained"; with the
start facts in the record, the service (or `symbiont nightly`) can start the server again and say
so, instead of leaving only "offline, figure it out". Pure: building the command text and reading
the record touch no process.
"""

import re
from dataclasses import asdict, dataclass
from typing import Any

from symbiont.service.nightly_backend import Backend

_PORT = re.compile(r":(\d+)/?$")


class JudgeStartError(RuntimeError):
    """The judge server could not be started, or did not answer in time."""


@dataclass(frozen=True)
class JudgeStart:
    """What `plug_judge_server.py` needs: the Python it runs on, the base, the adapter, the port."""

    python: str
    base: str
    adapter: str
    # "mps" on a Mac (the server cannot see it by itself), "cuda" with torch on NVIDIA; None lets
    # the server choose.
    device: str | None
    port: int

    def as_json(self) -> dict[str, Any]:
        """The fields as the nightly record stores them."""
        return asdict(self)

    def command_text(self, script: str) -> str:
        """The exact command that starts the server by hand."""
        prefix = "LCAP_DEVICE=mps " if self.device == "mps" else ""
        return (
            f"{prefix}{self.python} {script} --model {self.base} --adapter {self.adapter} "
            f"--port {self.port}"
        )


def judge_start_from_json(raw: Any) -> JudgeStart | None:
    """The start facts of a nightly record, or None when it has none or they are unusable."""
    try:
        device = raw["device"]
        fields = (str(raw["python"]), str(raw["base"]), str(raw["adapter"]))
        port = int(raw["port"])
    except (KeyError, TypeError, ValueError):
        return None
    return JudgeStart(*fields, device if isinstance(device, str) else None, port)


def port_of(url: str) -> int:
    """The port of a judge URL; JudgeStartError when it names none."""
    found = _PORT.search(url)
    if found is None:
        raise JudgeStartError(f"judge URL {url} names no port")
    return int(found.group(1))


def judge_device(backend: Backend) -> str:
    """The LCAP_DEVICE the judge server needs on this machine: mps with mlx, cuda with torch."""
    return "mps" if backend is Backend.MLX else "cuda"
