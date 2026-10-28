# Violation prevented: the thing  # expect: sym-no-framework-names-in-comments
# Sensor -> restore timing first  # expect: sym-no-framework-names-in-comments
LIMIT = 1  # avoids a Silent Fallback  # expect: sym-no-framework-names-in-comments


def labeled():
    """Guards against a Paper Tiger.  # expect: sym-no-framework-names-in-comments"""
    return 1
