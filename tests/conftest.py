from __future__ import annotations

from pathlib import Path

import pytest

from hr_compass import logging_setup


@pytest.fixture(autouse=True)
def isolated_logging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Keep tests from writing to the real logs/ folder and from leaking handlers into other tests."""
    monkeypatch.setenv(logging_setup.LOG_FILE_ENV, str(tmp_path / "test.log"))
    yield
    import logging

    logger = logging.getLogger("hr_compass")
    for handler in [h for h in logger.handlers if getattr(h, logging_setup._OWN, False)]:
        logger.removeHandler(handler)
        handler.close()
