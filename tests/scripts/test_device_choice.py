"""The torch scripts pick mps, then cuda, and refuse the CPU.

Violation prevented: Silent Fallback. No accelerator raises; it never returns "cpu".
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "routea"))
from device_choice import NoAcceleratorError, pick_device  # noqa: E402

BOTH = frozenset({"mps", "cuda"})
CUDA_ONLY = frozenset({"cuda"})
NONE = frozenset()
pytestmark = pytest.mark.periphery


def test_mps_is_preferred_then_cuda():
    assert pick_device(None, BOTH) == "mps"
    assert pick_device(None, CUDA_ONLY) == "cuda"


def test_a_requested_device_is_honored_when_available():
    assert pick_device("cuda", BOTH) == "cuda"


def test_no_accelerator_raises_instead_of_using_the_cpu():
    with pytest.raises(NoAcceleratorError, match="CPU"):
        pick_device(None, NONE)


def test_an_unavailable_or_unknown_request_raises():
    with pytest.raises(NoAcceleratorError, match="not available"):
        pick_device("mps", CUDA_ONLY)
    with pytest.raises(NoAcceleratorError, match="not one of"):
        pick_device("cpu", BOTH)
