# ledger

A small multi-currency billing ledger. Account balances are kept in USD cents.
Money rules are in docs/currencies.md.

This is a synthetic example for symbiont's "see it work" demo (a designed demo, not a measurement).
Its four tests fail on purpose, all for one reason: money code assumes two decimals, while the rule
is that amounts are integers in each currency's minor units. Pick a task with
`pytest -q -k credit_note`, `-k invoice`, `-k proration` or `-k refund`.
