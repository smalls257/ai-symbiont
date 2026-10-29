"""Errors ledgerline raises instead of guessing."""


class AmountFormatError(ValueError):
    """Text that is not an amount ledgerline can read."""


class UnknownCurrencyError(KeyError):
    """A currency code the rate table has no rate for."""
