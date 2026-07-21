"""
Solar2D MCP Tools - Tool definitions and dispatcher.
"""

from mcp.types import ImageContent, TextContent, Tool

from tools import configure, list_projects, read_logs, run_project, screenshot, social, solar_scope, state, touch, trello

# Collect all tools
TOOLS: list[Tool] = [
    configure.TOOL,
    run_project.TOOL,
    read_logs.TOOL,
    list_projects.TOOL,
    *screenshot.TOOLS,  # Include all screenshot tools
    *touch.TOOLS,  # Include touch simulation tools
    *state.TOOLS,  # Include game state and scenario tools
    *solar_scope.TOOLS,  # Include SolarScope test-runner tools
    *social.TOOLS,  # Include social media tools
    *trello.TOOLS,  # Include Trello tools
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
    "encode_recording_video": screenshot.handle_encode_video,
    "simulate_tap": touch.handle_simulate_tap,
    "simulate_drag": touch.handle_simulate_drag,
    "find_object": touch.handle_find_object,
    "get_display_info": touch.handle_get_display_info,
    "run_solar_scope_test": solar_scope.handle_run,
    "rerun_solar_scope_test": solar_scope.handle_rerun,
    "get_solar_scope_result": solar_scope.handle_get_result,
    **state.HANDLERS,  # Game state and scenario handlers
    **social.HANDLERS,  # Social media handlers
    **trello.HANDLERS,  # Trello handlers
}


async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
    """Dispatch a tool call to the appropriate handler."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)
