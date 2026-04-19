import pytest
from pathlib import Path


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """An empty project dir with a ./ralph/ subdir."""
    (tmp_path / "ralph").mkdir()
    return tmp_path


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
