"""Portable source and separately supplied participant-data locations."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASET_ROOT = Path(os.environ.get("GHOST_AUDIT_DATASET", PROJECT_ROOT / "dataset")).resolve()
