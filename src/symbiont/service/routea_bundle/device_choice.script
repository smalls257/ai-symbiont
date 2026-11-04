"""Which accelerator the torch scripts run on.

A box with neither Apple's GPU nor CUDA must stop with a sentence, not quietly train or serve on
the CPU at a fraction of the speed.
"""

DEVICES = ("mps", "cuda")


class NoAcceleratorError(RuntimeError):
    """Neither mps nor cuda is available, or the requested device is not usable here."""


def pick_device(requested: str | None, available: frozenset[str]) -> str:
    """The device to use: `requested` (LCAP_DEVICE) if usable, else mps, then cuda.

    `available` is the set of device names the installed torch reports as usable.

    Raises NoAcceleratorError for an unknown or unavailable request, and when nothing is available.
    """
    if requested:
        if requested not in DEVICES:
            raise NoAcceleratorError(f"LCAP_DEVICE={requested!r} is not one of {DEVICES}")
        if requested not in available:
            raise NoAcceleratorError(f"LCAP_DEVICE={requested} is not available on this machine")
        return requested
    for name in DEVICES:
        if name in available:
            return name
    raise NoAcceleratorError(
        "no accelerator: neither Apple mps nor CUDA is available. "
        "It will not fall back to the CPU; run on an Apple Silicon Mac or an NVIDIA GPU"
    )
