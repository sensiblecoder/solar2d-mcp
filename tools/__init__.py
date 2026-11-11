"""
Solar2D MCP Tools - Tool definitions and dispatcher.
"""

from mcp.types import ImageContent, TextContent, Tool

from tools import (
    art,
    configure,
    list_projects,
    read_logs,
    run_project,
    screenshot,
    social,
    solar_scope,
    state,
    touch,
    trello,
    video,
)

# Collect all tools
TOOLS: list[Tool] = [
    configure.TOOL,
    run_project.TOOL,
    read_logs.TOOL,
    list_projects.TOOL,
    *screenshot.TOOLS,  # Live / from-video stills
    *video.TOOLS,  # 60fps window video + social exports
    *touch.TOOLS,  # Include touch simulation tools
    *state.TOOLS,  # Include game state and scenario tools
    *solar_scope.TOOLS,  # Include SolarScope test-runner tools
    *social.TOOLS,  # Include social media tools
    *trello.TOOLS,  # Include Trello tools
    *art.TOOLS,  # Include AI art generation tools
]

# Map tool names to handlers
_HANDLERS = {
    "configure_solar2d": configure.handle,
    "run_solar2d_project": run_project.handle,
    "read_solar2d_logs": read_logs.handle,
    "list_running_projects": list_projects.handle,
    "get_simulator_screenshot": screenshot.handle_get_screenshot,
    "simulate_tap": touch.handle_simulate_tap,
    "simulate_drag": touch.handle_simulate_drag,
    "find_object": touch.handle_find_object,
    "get_display_info": touch.handle_get_display_info,
    "run_solar_scope_test": solar_scope.handle_run,
    "rerun_solar_scope_test": solar_scope.handle_rerun,
    "get_solar_scope_result": solar_scope.handle_get_result,
    **video.HANDLERS,  # Video recording handlers
    **state.HANDLERS,  # Game state and scenario handlers
    **social.HANDLERS,  # Social media handlers
    **trello.HANDLERS,  # Trello handlers
    **art.HANDLERS,  # AI art generation handlers
}


async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
    """Dispatch a tool call to the appropriate handler."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)
