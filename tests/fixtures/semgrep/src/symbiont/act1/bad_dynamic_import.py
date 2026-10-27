"""Fixture: dynamic imports the static allowlist cannot see. Every `# expect:` line must be reported."""

import importlib


def load(name):
    importlib.import_module("requests")  # expect: sym-dynamic-import
    importlib.import_module(name)  # expect: sym-dynamic-import
    __import__("httpx")  # expect: sym-dynamic-import
    __import__(name)  # expect: sym-dynamic-import
    importlib.import_module("urllib.request")  # expect: sym-dynamic-import
    importlib.import_module("numpy")
    importlib.import_module("symbiont.records.schema")
    __import__("json")


def builtins_import(name):
    import builtins

    builtins.__import__("requests")  # expect: sym-dynamic-import
    builtins.__import__(name)  # expect: sym-dynamic-import
    builtins.__import__("json")
