from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hr_compass.shared import logging as hr_logging


@pytest.fixture(autouse=True)
def isolated_logging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Keep tests from writing to the real logs/ folder and from leaking handlers into other tests; give pytest's
    caplog records the run_id / request_id / doc context fields."""
    monkeypatch.setenv(hr_logging.LOG_FILE_ENV, str(tmp_path / "test.log"))
    root = logging.getLogger()
    context = hr_logging.context_filter()
    for handler in root.handlers:
        handler.addFilter(context)
    yield
    for handler in root.handlers:
        handler.removeFilter(context)
    hr_logging.remove_handlers()
