"""Fixture: notes shown to a model must read as domain prose."""


def leaky(score, name):
    return f"Careful with {name}, risk score {score}"  # expect: sym-notes-are-prose


def leaky_format(threshold):
    return "past the {}".format(threshold)  # expect: sym-notes-are-prose


def prose(name, count):
    return f"{name} broke the build {count} times before"
