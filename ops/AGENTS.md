# ops: scripts that touch real machines

See root CLAUDE.md for the repo rules. This file covers `ops/`.

**Purpose.** `gpu_run.sh` runs one GPU job with the day-time model container out of the way; `secrets_scan.sh` is the scan before every push; `gpu_queue.md` is the job queue note.

**Violation prevented: Silent Fallback.** A crashed overnight job that leaves the day-time container stopped, or a secrets scan that "found nothing" because its tool was missing, both look fine until someone needs them. So `gpu_run.sh` restores the recorded state on every exit path and releases its lock, and `secrets_scan.sh` fails closed.

## Invariants
- GPU jobs only through `gpu_run.sh`; one at a time; touch only the named container; never sudo or apt; leave the other services running.
- Scripts take hosts and paths from the environment; no private address, hostname or user name is committed (gitleaks enforces it).
- No git rewrites or blanket `git add` here (semgrep `sym-no-git-rewrite`).
- Exit codes are documented in the script header.

## Commands
`ops/secrets_scan.sh` before every push; `bash -n ops/gpu_run.sh` after edits.

## Review focus
Every exit path: is state restored and the lock released? Does a new script hard-code a machine?
