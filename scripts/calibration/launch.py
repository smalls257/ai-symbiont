"""Entry point for the staged calibration driver: `python launch.py <workdir>`.

Prevents Silent Fallback at the start of a night-long run: a missing SYMBIONT_GLIMMER_URL
must stop the process with the variable's name before staged.py loads rows, builds the Driver
or writes a "finished" summary that sync_results.sh would read as a dead driver.
"""

import runpy
from pathlib import Path

from run_calibration import glimmer_url

if __name__ == "__main__":
    glimmer_url()
    runpy.run_path(str(Path(__file__).with_name("staged.py")), run_name="__main__")
