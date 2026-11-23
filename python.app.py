"""Project entry point for the Beam Designer desktop app."""

from __future__ import annotations

import sys
from pathlib import Path


APP_DIRECTORY = Path(__file__).resolve().parent / "04_app"
sys.path.insert(0, str(APP_DIRECTORY))

from app_window import run  # noqa: E402


if __name__ == "__main__":
    run()
