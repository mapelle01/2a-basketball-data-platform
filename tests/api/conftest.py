import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest

from api_helpers import make_client


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "feb.db")


@pytest.fixture
def client(db_path):
    return make_client(db_path)


@pytest.fixture
def client_factory():
    def _make(path, **kwargs):
        return make_client(path, **kwargs)
    return _make