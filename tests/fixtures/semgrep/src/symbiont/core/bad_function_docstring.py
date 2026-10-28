def long_function():  # expect: sym-docstring-too-long
    """Four lines is one over the function cap.
    two
    three
    four
    """
    return 1


class Holder:
    def long_method(self):  # expect: sym-docstring-too-long
        """Four lines.
        two
        three
        four"""
        return 1


async def long_coroutine():  # expect: sym-docstring-too-long
    """Four lines.
    two
    three
    four"""
    return 1
