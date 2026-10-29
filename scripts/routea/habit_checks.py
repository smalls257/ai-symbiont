"""The five kinds' check sentences, readable without MLX or torch.

`rank_habits.py` (MLX) holds the same function; it sits behind the scored-run freeze, so the CUDA
ranker reads this copy instead of editing frozen code. Fold the two together after the freeze.
"""

import importlib.util
from pathlib import Path

CHECKS_MODULE = Path(__file__).resolve().parent.parent / "aidev" / "lessons.py"


def checks() -> dict[str, str]:
    """Check sentence per kind value, read from the AIDev lessons module. Raises if it is absent."""
    spec = importlib.util.spec_from_file_location("aidev_lessons", CHECKS_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {kind.value: text for kind, text in module.CHECK.items()}
