"""Currency table."""

EXPONENTS = {"USD": 2, "EUR": 2, "JPY": 0, "BHD": 3, "KWD": 3}


def currency_exponent(code):
    """Decimal places of the currency's minor unit."""
    return EXPONENTS[code]
