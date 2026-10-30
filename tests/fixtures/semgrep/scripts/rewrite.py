"""Fixture: git rewrites spelled as argument lists."""

import subprocess

subprocess.run(["git", "reset", "--hard"], check=True)  # expect: sym-no-git-rewrite
subprocess.run(["git", "add", "-A"], check=True)  # expect: sym-no-git-rewrite
subprocess.run(["git", "diff", "--name-only"], check=True)
subprocess.run(["git", "add", "scripts/rewrite.py"], check=True)
