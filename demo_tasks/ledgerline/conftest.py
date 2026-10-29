"""Test session setup: rebuild generated code so no test runs against a stale grammar."""

from codegen.build_grammar import write_grammar


def pytest_sessionstart(session):
    """Regenerate ledgerline/_amount_grammar.py from its template before collection."""
    write_grammar()
