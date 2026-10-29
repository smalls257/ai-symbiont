"""Render ledgerline/_amount_grammar.py from codegen/amount_grammar.py.tmpl."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "codegen" / "amount_grammar.py.tmpl"
TARGET = ROOT / "ledgerline" / "_amount_grammar.py"
# ledgerline reads amounts in one notation; importers convert other locales before parsing.
SEPARATORS = {"group": ",", "decimal": "."}


def render_grammar(template: str) -> str:
    """Fill the template's slots: each separator as a literal and as a regex fragment."""
    text = template
    for name, char in SEPARATORS.items():
        text = text.replace("{{" + name + "_re}}", re.escape(char))
        text = text.replace("{{" + name + "}}", char)
    return text


def write_grammar() -> Path:
    """Write the generated module and return its path."""
    TARGET.write_text(render_grammar(TEMPLATE.read_text()))
    return TARGET


if __name__ == "__main__":
    write_grammar()
