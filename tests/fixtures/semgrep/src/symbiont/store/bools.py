"""Fixture: boolean arity."""


def two_flags(path, strict: bool, verbose: bool):  # expect: sym-no-bool-pair
    return path, strict, verbose


def keyword_pair(path, *, strict: bool = False, verbose: bool = True):  # expect: sym-no-bool-pair
    return path, strict, verbose


class Loader:
    def load(self, path, strict: bool, verbose: bool):  # expect: sym-no-bool-pair
        return path, strict, verbose


def one_flag(path, strict: bool):
    return path, strict


def flag_and_count(path, strict: bool, retries: int):
    return path, strict, retries
