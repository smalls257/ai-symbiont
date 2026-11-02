"""Money helpers."""


def to_minor(amount, currency=None):
    """'12.50' -> 1250."""
    return int(round(float(amount) * 100))


def format_major(minor, currency=None):
    """1250 -> '12.50'."""
    return f"{minor / 100:.2f}"


def convert_minor(minor, rate, currency=None):
    """Minor units of a charge currency -> USD cents at `rate`."""
    return int(round(minor * rate))
