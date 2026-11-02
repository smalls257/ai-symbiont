"""Today's rates (USD per one major unit)."""

TODAY = {"USD": 1.0, "EUR": 1.10, "JPY": 0.0070, "BHD": 2.65, "KWD": 3.25}


def current(code):
    """Today's rate for a currency code."""
    return TODAY[code]
