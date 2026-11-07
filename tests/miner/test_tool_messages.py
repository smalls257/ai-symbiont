from symbiont.miner.tool_messages import tool_message


def test_git_fatal_line():
    out = (
        "Exit code 128\nwarning: could not open directory 'a/b/'\n"
        "fatal: pathspec 'a/b/c.ts' did not match any files"
    )
    assert tool_message(out) == "fatal: pathspec <x> did not match any files"


def test_typescript_error_keeps_code_and_message():
    out = (
        "src/a.ts(101,9): error TS2353: Object literal may only specify known properties, "
        "and 'source' does not exist in type 'Res'."
    )
    assert tool_message(out) == (
        "error TS2353: Object literal may only specify known properties, "
        "and <x> does not exist in type <x>."
    )


def test_http_status_is_kept():
    out = "Exit code 1\nHTTP 401: Bad credentials (https://api.github.com/graphql)"
    assert tool_message(out) == "HTTP 401: Bad credentials (<url>)"


def test_zsh_eval_prefix_dropped():
    out = "(eval):1: no matches found: .planning/x/*.md"
    assert tool_message(out) == "no matches found: <path>"


def test_durations_normalized():
    assert tool_message("Command timed out after 2m 0s") == "Command timed out after <n>"


def test_apostrophe_is_not_a_quote():
    out = "fatal: unable to access 'https://x/': Couldn't connect to server"
    assert tool_message(out) == "fatal: unable to access <x>: Couldn't connect to server"


def test_husky_hook_failure():
    out = "husky - pre-commit script failed (code 1)"
    assert tool_message(out) == "husky - pre-commit script failed (code <n>)"


def test_no_complaint():
    assert tool_message("Exit code 1\n") is None
    assert tool_message("") is None


def test_prose_with_a_slash_is_not_a_path():
    assert tool_message("error: expected and/or here") == "error: expected and/or here"
    assert tool_message("error: read/write true/false") == "error: read/write true/false"


def test_real_paths_still_become_a_placeholder():
    assert tool_message("error: cannot open /etc/x/y.conf") == "error: cannot open <path>"
    assert tool_message("error: bad ./run and ~/x and a/b/c and a/b.py") == (
        "error: bad <path> and <path> and <path> and <path>"
    )
