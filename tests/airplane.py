"""QG-TST-06 (network part): airplane mode for unit tests; any socket use outside periphery tests
fails loudly. The disk and clock parts of the standard are not enforced yet."""


class AirplaneViolationError(RuntimeError):
    """A test not marked `periphery` tried to open a network socket."""


def refuse_network(*args, **kwargs):
    raise AirplaneViolationError(
        "network use in an airplane-mode test; mark it @pytest.mark.periphery "
        "if it belongs to the store, service or delivery layer"
    )
