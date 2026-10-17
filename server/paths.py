"""Local runtime inputs are separate from source; none are distributed by Git."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configured_path(name, default):
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


ASSETS = configured_path("BA_ASSET_DIR", ROOT / "local/assets/build-37822")
SIMULATION_DLL = configured_path("BA_SIMULATION_DLL", ASSETS / "Simulation.dll")
DATA = configured_path("BA_DATA_DIR", ROOT / "local/server-data")
