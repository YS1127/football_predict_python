import json
from pathlib import Path

import pytest


@pytest.fixture
def load_fixture():
    fixture_dir = Path(__file__).parent / "fixtures"

    def load(name: str) -> dict:
        with (fixture_dir / name).open(encoding="utf-8") as file:
            return json.load(file)

    return load
