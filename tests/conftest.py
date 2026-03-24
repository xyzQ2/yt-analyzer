"""Pytest configuration — downloads required NLTK corpora before test run."""

import nltk


def pytest_configure(config):
    """Download required NLTK data if not already present."""
    for corpus in ("stopwords", "punkt", "punkt_tab"):
        try:
            nltk.download(corpus, quiet=True)
        except Exception:
            pass
