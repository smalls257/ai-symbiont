"""Fixture: delivery reaches the service only through egress."""

import http.server  # expect: sym-single-egress
from symbiont.egress import Destination, Endpoint, post_json
