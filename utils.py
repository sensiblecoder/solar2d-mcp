"""
Shared utilities for Solar2D MCP Server.
"""

from pathlib import Path

# Corona Simulator path
CORONA_SIMULATOR = "/Applications/Corona-3726/Corona Simulator.app/Contents/MacOS/Corona Simulator"

# Track running Corona processes and their log files
running_projects = {}  # {project_path: {"pid": int, "log_file": str, "process": subprocess.Popen}}


def find_main_lua(project_path: str) -> str:
    """Find main.lua in the given project path."""
    path = Path(project_path)

    # If the path is already main.lua
    if path.name == "main.lua" and path.exists():
        return str(path.absolute())

    # If the path is a directory, look for main.lua inside
    if path.is_dir():
        main_lua = path / "main.lua"
        if main_lua.exists():
            return str(main_lua.absolute())

    # If neither works, return the original path (will error later)
    return str(Path(project_path).absolute())
