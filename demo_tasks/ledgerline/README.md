# ledgerline

A small bookkeeping library: amounts, customer statements, VAT and currency conversion.

Constructed demo task repository for ai-symbiont (not a benchmark). Every bug in it was
written on purpose so a coding agent has something realistic to fix.

- `ledgerline/money.py`: amounts and parsing (`parse_amount`)
- `ledgerline/statement.py`: aging report for open invoices
- `ledgerline/tax/`: VAT rules, one module per country on top of `tax/vat.py`
- `ledgerline/fx.py`: conversion through a table of rates
- `codegen/`: the generator for `ledgerline/_amount_grammar.py`

See CONTRIBUTING.md before running the tests.
