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


def test_an_arithmetic_shift_does_not_arm_a_heredoc():
    from symbiont.miner.commands import program_words, status_program

    command = "x=$((1<<2))\nls tests"
    assert program_words(command)[0] == "ls"
    assert status_program(command) == "ls"
    assert program_words("((x<<=1))\nls")[0] == "ls"
    assert "<<" not in shell_text("x=$((1<<2))\nls tests")


def test_a_mid_line_comment_ends_the_line_for_quote_tracking():
    assert _flat("ls # it's here\ngit status") == "ls ; git status"


def test_a_hash_inside_a_word_is_not_a_comment():
    assert _flat("echo a#b 'x\ny'") == "echo a#b 'x y'"
    assert _flat("echo ${#x} 'it\ns'\nls") == "echo ${#x} 'it s' ; ls"


def test_a_line_ending_in_an_operator_continues_on_the_next():
    assert _flat("make &&\nmake test") == "make && make test"
    assert _flat("a ||\nb") == "a || b"
    assert _flat("cat x |\ngrep y") == "cat x | grep y"
