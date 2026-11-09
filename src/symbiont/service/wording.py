"""Counts in plain English, so a page or a terminal never says "1 sessions"."""


def counted(number: int, noun: str) -> str:
    """`1 session`, `2 sessions`: a regular plural by adding an s."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"
