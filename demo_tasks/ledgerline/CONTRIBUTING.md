# Contributing to ledgerline

## Running the tests

    pytest tests/test_statement.py

Run the test file for the code you touched. `tests/soak/` holds soak tests that each run for a
fixed time budget; the whole suite takes minutes.

The currency tests in `tests/rates/` read a frozen rate snapshot. Point them at it first:

    export LEDGERLINE_FIXTURES=tests/rates/fixtures/2024-06

The other snapshot directories are kept for old regression reports; the current tests are written
against 2024-06.

## Generated code

`ledgerline/_amount_grammar.py` is generated from `codegen/amount_grammar.py.tmpl` by
`python -m codegen.build_grammar`. The root `conftest.py` rebuilds it at the start of every test
run, so edit the template, never the generated file.

## Tax rules

`ledgerline/tax/vat.py` holds the shared VAT arithmetic. Country rules live in their own module
(`de.py`, `ch.py`, `gb.py`) and override only what differs for that country. Do not change the
shared default for one country.
