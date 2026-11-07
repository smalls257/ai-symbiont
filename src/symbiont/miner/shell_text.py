"""A multi-line shell command as the one line the shell would run.

Heredoc bodies and comment lines are dropped, backslash continuations are joined and
every newline outside quotes becomes ` ; `, so the tokenizer sees real commands.
"""

import re

_HEREDOC = re.compile(r"<<[-~]?[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|([\w.-]+))")
_SEPARATOR = " ; "


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
        elif char == "#" and self.line_blank:
            self._drop_comment_line()
        elif char == "\\":
            self._take(2)
        elif char in "'\"":
            self.quote = char
            self._take(1)
        elif self.text.startswith("<<", self.pos) and self._arm_heredoc():
            return
        else:
            self._take(1)

    def _take(self, count: int) -> None:
        chunk = self.text[self.pos : self.pos + count]
        self.out.append(chunk)
        self.pos += count
        if chunk.strip():
            self.line_blank = False

    def _newline(self) -> None:
        self.pos += 1
        self._skip_heredoc_bodies()
        self.line_blank = True
        if self.out and self.out[-1] != _SEPARATOR:
            self.out.append(_SEPARATOR)

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
