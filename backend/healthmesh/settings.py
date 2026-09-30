from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_path


def data_directory() -> Path:
    override = os.getenv("HEALTHMESH_DATA_DIR")
    path = Path(override).expanduser() if override else user_data_path("HealthMesh", appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def frontend_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def fixtures_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures"

