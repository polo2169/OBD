import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolate_diagnostic_history(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "diagnostic_history_dir", tmp_path / "diagnostics")

