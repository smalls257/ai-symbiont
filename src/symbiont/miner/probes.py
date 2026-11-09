"""The programs that only look around; a leaf module so both screen and read_only can use it."""

# Read-only look-around programs: a failure of one is the agent feeling its way, not a trap.
PROBES = frozenset(
    {"ls", "cat", "head", "tail", "find", "stat", "file", "which", "pwd", "wc", "grep", "rg"}
)
