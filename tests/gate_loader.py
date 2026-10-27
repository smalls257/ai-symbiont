"""Load the gate scripts under scripts/gates/ as modules, so their logic is unit-tested
without shelling out. The scripts stay runnable files; this is only a test seam."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[1]
GATES = REPO / "scripts" / "gates"


def load_gate(name: str) -> ModuleType:
    """Import scripts/gates/<name>.py under the module name `gate_<name>`."""
    module_name = f"gate_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, GATES / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"gate script not found: {GATES / (name + '.py')}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
