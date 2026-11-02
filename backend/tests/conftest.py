import pytest
from ads_optimizer.api import app
from ads_optimizer.data.repository import Repository, get_repository


@pytest.fixture(autouse=True)
def isolated_repository(tmp_path):
    repo = Repository(tmp_path / "workspace")
    app.dependency_overrides[get_repository] = lambda: repo
    yield repo
    app.dependency_overrides.clear()
