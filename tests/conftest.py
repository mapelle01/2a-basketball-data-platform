"""Suite-wide defaults.

Rendering can pull official portraits from FEB over the network. That is right
in production and wrong in a test suite: it would make results depend on an
external host being up, and slow every pipeline test down by the round trips.
Tests therefore run with the statistical (initials) provider unless one opts in
explicitly; the provider itself is covered directly with an injected fetch.
"""
import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _no_official_images():
    previous = os.environ.get("FEB_SCORE_OFFICIAL_IMAGES")
    os.environ["FEB_SCORE_OFFICIAL_IMAGES"] = "0"
    yield
    if previous is None:
        os.environ.pop("FEB_SCORE_OFFICIAL_IMAGES", None)
    else:
        os.environ["FEB_SCORE_OFFICIAL_IMAGES"] = previous
