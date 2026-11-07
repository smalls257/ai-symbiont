from symbiont.miner.shell_text import shell_text


def _flat(command: str) -> str:
    return " ".join(shell_text(command).split())


def test_newlines_become_separators():
    assert _flat("cd /repo\ngit push") == "cd /repo ; git push"


def test_heredoc_body_is_dropped():
    command = "cat > f.md << 'EOF'\n## it's a body\nEOF\ngit add f.md"
    assert _flat(command) == "cat > f.md << 'EOF' ; git add f.md"


def test_comment_lines_are_dropped():
    assert _flat("# look around\nfind /usr -name x") == "find /usr -name x"


def test_continuation_is_joined():
    assert _flat("gh api x \\\n  --jq '.body'") == "gh api x --jq '.body'"


def test_newline_inside_quotes_is_kept():
    command = "gh api graphql -f query='\nquery {\n}'"
    assert shell_text(command) == command


def test_unbalanced_multiline_falls_back_to_first_line():
    assert shell_text('echo "it\nnever closes') == 'echo "it'


def test_herestring_does_not_arm_a_heredoc():
    assert _flat("grep x <<< foo\nls") == "grep x <<< foo ; ls"
