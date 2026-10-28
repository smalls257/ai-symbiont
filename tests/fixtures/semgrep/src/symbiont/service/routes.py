"""Fixture: the exclusion is one file, not the service package."""

import urllib.request  # expect: sym-single-egress
from http.server import HTTPServer  # expect: sym-single-egress
import json
from symbiont.records import schema
