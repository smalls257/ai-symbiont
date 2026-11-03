"""Test modules for tooling that is POSIX by nature, and so not collected on Windows.

Why: these drive bash scripts, gitleaks, node, ssh, fork-based worker pools, `#!` trainers or
chmod modes on the Linux CI job, the dev machine and the GPU host. Windows users run none of that;
what they run (hooks, service, MCP server, installer, readers, dashboard, CLI) is tested in the
other modules. The Windows counterpart is tests/test_shell_scripts_parse.py (every script parses
under Git Bash with LF line ends) and tests/test_posix_tooling_list.py (this list names real files).
"""

import sys

POSIX_TOOLING_TESTS = (
    "gates/test_check_export.py",
    "gates/test_claude_hooks.py",
    "gates/test_frontend_gates.py",
    "gates/test_gitleaks_rules.py",
    "gates/test_private_terms.py",
    "gates/test_registry_gate.py",
    "gates/test_run_script.py",
    "gates/test_shell_gates.py",
    "gates/test_wired_gates.py",
    "ops/test_gpu_run.py",
    "scripts/test_fetch_swe_chat.py",
    "scripts/test_launch_general_pilot.py",
    "scripts/test_loop_units.py",
    "scripts/test_routea_end_to_end.py",
    "scripts/test_routeb_nightly.py",
    "scripts/test_run_meta_start.py",
    "scripts/test_run_selection.py",
    "scripts/test_sync_results_env.py",
    "scripts/test_sync_results_probe.py",
)


def ignored_here() -> list[str]:
    """The modules pytest must not collect on this platform: all of them on Windows, else none."""
    return list(POSIX_TOOLING_TESTS) if sys.platform == "win32" else []
