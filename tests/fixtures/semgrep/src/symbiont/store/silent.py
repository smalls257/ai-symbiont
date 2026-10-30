"""Fixture: swallowed exceptions and prints in library code."""

import logging

log = logging.getLogger(__name__)


def swallow_pass(path):
    try:  # expect: sym-no-silent-except
        return open(path).read()
    except OSError:
        pass


def swallow_none(path):
    try:  # expect: sym-no-silent-except
        return open(path).read()
    except OSError as err:
        return None


def swallow_continue(paths):
    for path in paths:
        try:  # expect: sym-no-silent-except
            open(path).read()
        except OSError:
            continue


def swallow_bare(path):
    try:  # expect: sym-no-silent-except
        return open(path).read()
    except:
        log.exception("failed")


def chatty(value):
    print(value)  # expect: sym-no-print-in-library


def logged_and_raised(path):
    try:
        return open(path).read()
    except OSError:
        log.exception("cannot read %s", path)
        raise


def typed_failure(path):
    try:
        return open(path).read()
    except OSError as err:
        raise RuntimeError(f"cannot read {path}") from err


def narrated(value):
    log.info("value %s", value)
