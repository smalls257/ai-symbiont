#!/usr/bin/env python3
# Copyright (c) the authors
# License: MIT
# SPDX-License-Identifier: MIT
# a header with a license line may run long
"""Six content lines is the module cap.
two
three
four
five
Usage: good_comments.py FILE
six
"""

# three comment lines are allowed
# so are these
# and this one
PLAIN = 1
MESSAGE = "failing text may say Silent Fallback or Paper Tiger"
LIMIT = 2  # inline comments do not form a block
OTHER = 3  # inline comments do not form a block
THIRD = 4  # inline comments do not form a block
FOURTH = 5  # inline comments do not form a block


def three_lines():
    """Three lines is the function cap.
    two
    three"""
    return 1


class Roomy:
    """Five lines is the class cap.
    two
    three
    four
    five"""


def filter_rows(rows):
    """Filter rows by id; the engine buffers input, a sensor of anchor points."""
    return rows
