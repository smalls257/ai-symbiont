"""Fixture: an Infected Core. Every `# expect:` line must be reported, nothing else."""

import os
import socket  # expect: sym-core-no-env sym-single-egress
import subprocess  # expect: sym-core-no-env
import urllib.request  # expect: sym-core-no-env sym-single-egress
from datetime import datetime
from time import monotonic  # expect: sym-core-no-env
import random


def stamp():
    return datetime.now()  # expect: sym-core-no-env


def token():
    return os.environ["TOKEN"]  # expect: sym-core-no-env


def roll():
    return random.random()  # expect: sym-core-no-env


def read():
    with open("x") as fh:  # expect: sym-core-no-env
        return fh.read()
