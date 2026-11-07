"""A multi-line shell command as the one line the shell would run.

Heredoc bodies and comment lines are dropped, backslash continuations are joined and
every newline outside quotes becomes ` ; `, so the tokenizer sees real commands. A line that
ends in `&&`, `||` or `|` continues on the next one.
"""

import re

_HEREDOC = re.compile(r"<<[-~]?[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|([\w.-]+))")
_ARITHMETIC = re.compile(r"\(\([^\n]*?\)\)")
_SEPARATOR = " ; "
_CONTINUATION = " "
_OPEN_OPERATORS = ("&&", "|")


def shell_text(command: str) -> str:
    """The command as one shell line; the first line alone when a quote never closes."""
    text = command.strip()
    scan = _Scan(text)
    scan.run()
    if scan.quote:
        # An open quote means free text we cannot parse; the first line is all we trust.
        return text.splitlines()[0] if text else ""
    return "".join(scan.out).strip()


class _Scan:
    """Left-to-right pass tracking quotes, comment lines and armed heredocs."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.out: list[str] = []
        self.quote = ""
        self.line_blank = True
        self.heredoc_words: list[str] = []
        self.break_pending = False

    def run(self) -> None:
        while self.pos < len(self.text):
            if self.quote:
                self._inside_quote()
            else:
                self._outside_quote()

    def _inside_quote(self) -> None:
        char = self.text[self.pos]
        if char == "\\" and self.quote == '"' and self.pos + 1 < len(self.text):
            self._take(2)
            return
        if char == self.quote:
            self.quote = ""
        self._take(1)

    def _outside_quote(self) -> None:
        char = self.text[self.pos]
        if char == "\n":
            self._newline()
        elif char == "\\" and self.text[self.pos + 1 : self.pos + 2] == "\n":
            self.pos += 2
        elif char == "#" and (self.line_blank or self.text[self.pos - 1].isspace()):
            self._drop_comment()
        elif char == "\\":
            self._take(2)
        elif char in "'\"":
            self.quote = char
            self._take(1)
        elif not self._take_construct():
            self._take(1)

    def _take_construct(self) -> bool:
        """Consume `((...))` or a heredoc opener when one starts here."""
        if self.text.startswith("((", self.pos):
            return self._drop_arithmetic()
        return self.text.startswith("<<", self.pos) and self._arm_heredoc()

    def _take(self, count: int) -> None:
        chunk = self.text[self.pos : self.pos + count]
        self.out.append(chunk)
        self.pos += count
        if chunk.strip():
            self.line_blank = False
            self.break_pending = False

    def _newline(self) -> None:
        self.pos += 1
        self._skip_heredoc_bodies()
        self.line_blank = True
        if not self.out or self.break_pending:
            return
        self.break_pending = True
        self.out.append(_CONTINUATION if self._ends_in_operator() else _SEPARATOR)

    def _ends_in_operator(self) -> bool:
        tail = "".join(self.out[-8:]).rstrip()
        return tail.endswith(_OPEN_OPERATORS)

    def _drop_arithmetic(self) -> bool:
        """Keep `(())` for `((x<<=1))` and `$((1<<2))`: a shift inside is no heredoc."""
        match = _ARITHMETIC.match(self.text, self.pos)
        if not match:
            return False
        self.out.append("(())")
        self.pos = match.end()
        self.line_blank = False
        self.break_pending = False
        return True

    def _drop_comment(self) -> None:
        """A comment line goes whole; a trailing comment goes up to its newline."""
        if self.line_blank:
            self._drop_comment_line()
        else:
            self._drop_comment_tail()

    def _drop_comment_tail(self) -> None:
        end = self.text.find("\n", self.pos)
        self.pos = len(self.text) if end < 0 else end

    def _drop_comment_line(self) -> None:
        end = self.text.find("\n", self.pos)
        self.pos = len(self.text) if end < 0 else end + 1
        self.line_blank = True

    def _arm_heredoc(self) -> bool:
        if self.text.startswith("<<<", self.pos):
            self._take(3)
            return True
        match = _HEREDOC.match(self.text, self.pos)
        if not match:
            return False
        self.heredoc_words.append(next(group for group in match.groups() if group is not None))
        self._take(match.end() - self.pos)
        return True

    def _skip_heredoc_bodies(self) -> None:
        for word in self.heredoc_words:
            while self.pos < len(self.text):
                end = self.text.find("\n", self.pos)
                end = len(self.text) if end < 0 else end
                line = self.text[self.pos : end].strip()
                self.pos = min(end + 1, len(self.text))
                if line == word:
                    break
        self.heredoc_words = []
