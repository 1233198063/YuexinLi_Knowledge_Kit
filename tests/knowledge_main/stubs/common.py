"""Placeholder for the other runtime's internal module, so its test files import; tests that use it are not applicable here."""


class Context:
    def __init__(self, *a, **k):
        raise NotImplementedError("internal API of the other runtime")
