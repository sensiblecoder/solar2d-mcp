"""
Solar2D MCP Tools - Tool definitions and dispatcher.
"""

from mcp.types import Tool, TextContent

from tools import run_project, read_logs, list_projects, configure


# Collect all tools
TOOLS: list[Tool] = [
    configure.TOOL,
    run_project.TOOL,
    read_logs.TOOL,
    list_projects.TOOL,
]

# Map tool names to handlers
_HANDLERS = {
    "configure_solar2d": configure.handle,
    "run_solar2d_project": run_project.handle,
    "read_solar2d_logs": read_logs.handle,
    "list_running_projects": list_projects.handle,
}


async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch a tool call to the appropriate handler."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)
