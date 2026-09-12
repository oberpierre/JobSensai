"""Exceptions raised by the adapter-learning flows, kept out of ``worker.py`` so a
learning module that raises them can import them without importing the worker."""


class UnlearnablePage(Exception):
    """The truth agent grounded nothing on the page, so there is no adapter to write."""


class TruthAgentUnreadable(Exception):
    """The truth agent's reply could not be parsed, so the page was never assessed."""
