"""
read_solar2d_logs tool - Read console logs from a running Solar2D Simulator.
"""

import os
import tempfile
from pathlib import Path

from mcp.types import Tool, TextContent

from utils import find_main_lua


TOOL = Tool(
    name="read_solar2d_logs",
    description="Read the console logs from a running Solar2D Simulator instance. Shows print() statements, errors, and debug output from your Lua code.",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            },
            "lines": {
                "type": "number",
                "description": "Number of recent log lines to read (default: 50)",
                "default": 50
            }
        },
        "required": ["project_path"]
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle read_solar2d_logs tool call."""
    project_path = arguments.get("project_path")
    lines = arguments.get("lines", 50)

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    # Find the project directory
    main_lua_path = find_main_lua(project_path)
    project_dir = str(Path(main_lua_path).parent)

    # Compute expected log file path (works for both MCP-launched and manual launches)
    project_name = Path(project_dir).name
    log_file = os.path.join(tempfile.gettempdir(), f"corona_log_{project_name}.txt")

    # Read the log file
    try:
        if not os.path.exists(log_file):
            return [TextContent(
                type="text",
                text=f"Log file not found: {log_file}\n\nPossible reasons:\n- The project hasn't been launched yet (with or without MCP)\n- The _mcp_logger hasn't been injected yet (run project via MCP once to inject it)\n- The simulator hasn't produced any output yet"
            )]

        with open(log_file, 'r') as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        if not recent_lines:
            return [TextContent(
                type="text",
                text="No log output available yet. The simulator may still be starting up."
            )]

        log_content = ''.join(recent_lines)
        return [TextContent(
            type="text",
            text=f"Solar2D Simulator Logs (last {len(recent_lines)} lines):\n\n{log_content}"
        )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=f"Error reading log file: {str(e)}"
        )]
