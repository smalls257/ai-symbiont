# Known limits: the comment rules read raw text, so a "#" inside a string literal counts.
URL = "#Black Box"  # expect: sym-no-framework-names-in-comments
TEMPLATE = """
# a hook template written as a string  # expect: sym-comment-block-too-long
# four lines long
# so the block cap fires
# although no comment exists
"""


def plural():
    """Violations prevented: see the plan.  # expect: sym-no-framework-names-in-comments"""
    return 1
