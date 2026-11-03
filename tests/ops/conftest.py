"""ops/*.sh drive docker, flock and POSIX signals on a Linux GPU host; they cannot run on Windows.

On Windows this directory is not collected, and tests/test_shell_scripts_parse.py is the Windows
counterpart: every shell script must still parse under Git Bash and keep LF line ends.
"""

import sys

collect_ignore = ["test_gpu_run.py"] if sys.platform == "win32" else []
