"""How the nightly job reaches the training host: ssh for each host step, scp for the rows.

Every host step is one call of `ops/routeb_nightly_host.sh` on the host; its exit code comes back
as a `HostStepError` naming the step, never as a quiet `False`. A dry run prints the exact
command it would run and runs nothing. Lives in scripts/, not src/: `src/` may reach the network
only through `symbiont.egress` (semgrep `sym-network-subprocess` refuses ssh and scp there).
"""

import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path

from nightly_config import HostConfig

# Host exit 70: Glimmer could not be brought back (ops/routeb_nightly_host.sh header).
GLIMMER_DOWN = 70
# No password prompt can hang an unattended night; a dead link fails within a minute.
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=60")


class HostStepError(RuntimeError):
    """A host step exited non-zero; `glimmer_down` when the host could not restore Glimmer."""

    def __init__(self, step: str, code: int):
        """Name the step and its exit code."""
        down = " (GLIMMER IS DOWN: look now)" if code == GLIMMER_DOWN else ""
        super().__init__(f"host step {step!r} failed with exit {code}{down}")
        self.step = step
        self.code = code

    @property
    def glimmer_down(self) -> bool:
        """True when the host reported it could not bring Glimmer back."""
        return self.code == GLIMMER_DOWN


class TrainingHost:
    """The training host, driven over ssh; each method is one host step."""

    def __init__(self, config: HostConfig):
        """Keep the host's ssh destination, checkout and env file."""
        self.config = config

    def step(self, name: str, *args: str) -> None:
        """Run one host step; raises HostStepError on a non-zero exit."""
        remote = shlex.join([self.config.host_script, "--env", self.config.env_file, name, *args])
        self._call(name, ["ssh", *SSH_OPTIONS, self.config.ssh, remote])

    def upload(self, files: Sequence[Path], host_dir: str) -> None:
        """Make `host_dir` and copy `files` (directories recursively) into it."""
        self._call(
            "mkdir", ["ssh", *SSH_OPTIONS, self.config.ssh, shlex.join(["mkdir", "-p", host_dir])]
        )
        self._call(
            "upload",
            ["scp", *SSH_OPTIONS, "-q", "-r", *map(str, files), f"{self.config.ssh}:{host_dir}/"],
        )

    def _call(self, name: str, argv: list[str]) -> None:
        code = subprocess.run(argv, check=False).returncode
        if code != 0:
            raise HostStepError(name, code)


class DryRunHost(TrainingHost):
    """Prints each command it would run and runs nothing."""

    def __init__(self, config: HostConfig, say):
        """`say` prints one line (the nightly job's step printer)."""
        super().__init__(config)
        self.say = say

    def _call(self, name: str, argv: list[str]) -> None:
        self.say(f"  would run: {shlex.join(argv)}")
