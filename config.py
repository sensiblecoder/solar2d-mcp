"""
Configuration management for Solar2D MCP Server.
Auto-detects Solar2D location and persists user preferences.
"""

import json
import os
from pathlib import Path
from glob import glob


CONFIG_DIR = Path.home() / ".config" / "solar2d-mcp"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Common locations to search for Solar2D Simulator
SEARCH_PATHS = [
    "/Applications/Corona*/Corona Simulator.app/Contents/MacOS/Corona Simulator",
    "/Applications/Solar2D*/Solar2D Simulator.app/Contents/MacOS/Solar2D Simulator",
    str(Path.home() / "Applications/Corona*/Corona Simulator.app/Contents/MacOS/Corona Simulator"),
    str(Path.home() / "Applications/Solar2D*/Solar2D Simulator.app/Contents/MacOS/Solar2D Simulator"),
]


def _find_simulators() -> list[str]:
    """Find all Solar2D/Corona simulators on the system."""
    found = []
    for pattern in SEARCH_PATHS:
        matches = glob(pattern)
        found.extend(matches)
    # Sort by path (usually gets newest version last due to version numbers)
    return sorted(set(found))


def _load_config() -> dict:
    """Load config from file, or return empty dict if not found."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_config(config: dict) -> None:
    """Save config to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def get_simulator_path() -> str | None:
    """Get the configured simulator path, or None if not configured."""
    config = _load_config()
    return config.get("simulator_path")


def set_simulator_path(path: str) -> None:
    """Set and persist the simulator path."""
    config = _load_config()
    config["simulator_path"] = path
    _save_config(config)


def is_configured() -> bool:
    """Check if the simulator path has been configured."""
    path = get_simulator_path()
    return path is not None and os.path.exists(path)


def detect_simulators() -> list[str]:
    """Detect available Solar2D simulators on the system."""
    return _find_simulators()


def get_simulator_or_detect() -> tuple[str | None, list[str], bool]:
    """
    Get simulator path, detecting if needed.

    Returns:
        (configured_path, detected_paths, needs_confirmation)
        - configured_path: The saved path if valid, or best detected path
        - detected_paths: All detected simulator paths
        - needs_confirmation: True if user should confirm the path
    """
    config = _load_config()
    saved_path = config.get("simulator_path")
    detected = _find_simulators()

    # If we have a saved path and it still exists, use it
    if saved_path and os.path.exists(saved_path):
        return saved_path, detected, False

    # If saved path is invalid, clear it
    if saved_path and not os.path.exists(saved_path):
        config.pop("simulator_path", None)
        _save_config(config)

    # Return best detected path, but needs confirmation
    best_path = detected[-1] if detected else None  # Latest version
    return best_path, detected, True
