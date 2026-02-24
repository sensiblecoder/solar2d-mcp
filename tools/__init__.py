"""
Solar2D MCP Tools - Tool definitions and dispatcher.
"""

from mcp.types import Tool, TextContent, ImageContent

from tools import run_project, read_logs, list_projects, configure, screenshot, touch, social


# Collect all tools
TOOLS: list[Tool] = [
    configure.TOOL,
    run_project.TOOL,
    read_logs.TOOL,
    list_projects.TOOL,
    *screenshot.TOOLS,  # Include all screenshot tools
    *touch.TOOLS,  # Include touch simulation tools
    *social.TOOLS,  # Include social media tools
]

# Map tool names to handlers
_HANDLERS = {
    "configure_solar2d": configure.handle,
    "run_solar2d_project": run_project.handle,
    "read_solar2d_logs": read_logs.handle,
    "list_running_projects": list_projects.handle,
    "start_screenshot_recording": screenshot.handle_start_recording,
    "stop_screenshot_recording": screenshot.handle_stop_recording,
    "get_simulator_screenshot": screenshot.handle_get_screenshot,
    "list_screenshots": screenshot.handle_list_screenshots,
    "simulate_tap": touch.handle_simulate_tap,
    "get_display_info": touch.handle_get_display_info,
    **social.HANDLERS,  # Social media handlers
}


async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
    """Dispatch a tool call to the appropriate handler."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)
