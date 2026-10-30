"""AST scanners behind the boundary tests.

The pure core must not reach the network, the clock, subprocesses or the
periphery packages (store, service, delivery, readers). Packages must not
reach into each other's `_private` names.
"""

import ast

FORBIDDEN_MODULES = (
    "socket",
    "http",
    "urllib",
    "requests",
    "sqlite3",
    "subprocess",
    "time",
    "symbiont.store",
    "symbiont.service",
    "symbiont.delivery",
    "symbiont.readers",
)
CLOCK_CALLS = ("now", "utcnow", "today")


def _is_forbidden(module: str) -> bool:
    return any(module == f or module.startswith(f + ".") for f in FORBIDDEN_MODULES)


def _clock_call(node: ast.AST) -> str | None:
    """`datetime.now()`, `datetime.datetime.now()`, `date.today()` read the clock."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return None
    if node.func.attr not in CLOCK_CALLS:
        return None
    owner = node.func.value
    owner_name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
    if owner_name in ("datetime", "date"):
        return f"datetime.{node.func.attr}"
    return None


def impure_imports(source: str) -> list[str]:
    """Forbidden imports and clock reads in `source`, in source order."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names if _is_forbidden(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module and _is_forbidden(node.module):
            found.append((node.lineno, node.module))
        elif clock := _clock_call(node):
            found.append((node.lineno, clock))
    return [name for _, name in sorted(found)]


def _is_private(part: str) -> bool:
    return part.startswith("_") and not (part.startswith("__") and part.endswith("__"))


def _other_package_private(dotted: str, own_package: str) -> bool:
    parts = dotted.split(".")
    if parts[0] != "symbiont" or len(parts) < 2 or parts[1] == own_package:
        return False
    return any(_is_private(p) for p in parts)


def private_cross_imports(source: str, own_package: str) -> list[str]:
    """Dotted names of `_private` symbols imported from another symbiont package."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            dotted = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            dotted = [f"{node.module}.{a.name}" for a in node.names]
        else:
            continue
        found += [(node.lineno, d) for d in dotted if _other_package_private(d, own_package)]
    return [name for _, name in sorted(found)]
