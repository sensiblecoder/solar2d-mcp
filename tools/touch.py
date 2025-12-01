"""
Touch simulation tools - Simulate taps on the Solar2D simulator.
"""

import json
import os
import tempfile
from pathlib import Path

from mcp.types import Tool, TextContent

from utils import find_main_lua


# Tool definitions
SIMULATE_TAP_TOOL = Tool(
    name="simulate_tap",
    description="Simulate a tap/click in the Solar2D simulator. Specify a bounding box using percentages and the tool taps the center. Example: a button spanning 30-50% horizontally and 60-70% vertically would use left=30, right=50, top=60, bottom=70.",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            },
            "left": {
                "type": "number",
                "description": "Left edge of target as percentage (0=left edge of screen)"
            },
            "right": {
                "type": "number",
                "description": "Right edge of target as percentage (100=right edge of screen)"
            },
            "top": {
                "type": "number",
                "description": "Top edge of target as percentage (0=top of screen)"
            },
            "bottom": {
                "type": "number",
                "description": "Bottom edge of target as percentage (100=bottom of screen)"
            }
        },
        "required": ["project_path", "left", "right", "top", "bottom"]
    }
)

GET_DISPLAY_INFO_TOOL = Tool(
    name="get_display_info",
    description="Get the Solar2D display coordinate system. Call this before tapping to understand how screenshot pixels map to tap coordinates. Screenshots are captured at contentWidth x contentHeight. Tap coordinates use the same content space.",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            }
        },
        "required": ["project_path"]
    }
)

# Export all tools
TOOLS = [SIMULATE_TAP_TOOL, GET_DISPLAY_INFO_TOOL]


def _get_project_name(project_path: str) -> str:
    """Get the project name from the path."""
    main_lua_path = find_main_lua(project_path)
    project_dir = str(Path(main_lua_path).parent)
    return Path(project_dir).name


def _get_control_file(project_name: str) -> str:
    """Get the touch control file path."""
    return os.path.join(tempfile.gettempdir(), f"solar2d_touch_{project_name}.control")


def _get_info_file(project_name: str) -> str:
    """Get the display info output file path."""
    return os.path.join(tempfile.gettempdir(), f"solar2d_display_{project_name}.json")


async def handle_simulate_tap(arguments: dict) -> list[TextContent]:
    """Handle simulate_tap tool call."""
    project_path = arguments.get("project_path")
    left = arguments.get("left")
    right = arguments.get("right")
    top = arguments.get("top")
    bottom = arguments.get("bottom")

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    if None in (left, right, top, bottom):
        return [TextContent(type="text", text="Error: left, right, top, bottom are all required")]

    project_name = _get_project_name(project_path)
    control_file = _get_control_file(project_name)
    info_file = _get_info_file(project_name)

    # Read display info to convert percentages to coordinates
    if not os.path.exists(info_file):
        return [TextContent(
            type="text",
            text="Display info not found. Make sure the simulator is running."
        )]

    try:
        with open(info_file, 'r') as f:
            info = json.load(f)
        content_width = info.get('contentWidth')
        content_height = info.get('contentHeight')

        if not content_width or not content_height:
            return [TextContent(type="text", text="Error: Invalid display info")]

        # Calculate center of bounding box and convert to pixels
        x_percent = (left + right) / 2
        y_percent = (top + bottom) / 2
        x = int(content_width * x_percent / 100)
        y = int(content_height * y_percent / 100)

    except Exception as e:
        return [TextContent(type="text", text=f"Error reading display info: {str(e)}")]

    # Write tap command to control file
    command = f"tap,{x},{y}"
    with open(control_file, 'w') as f:
        f.write(command)

    return [TextContent(
        type="text",
        text=f"Tap sent to center of box ({left}-{right}%, {top}-{bottom}%)"
    )]


async def handle_get_display_info(arguments: dict) -> list[TextContent]:
    """Handle get_display_info tool call."""
    project_path = arguments.get("project_path")

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    project_name = _get_project_name(project_path)
    info_file = _get_info_file(project_name)

    if not os.path.exists(info_file):
        return [TextContent(
            type="text",
            text="Display info not found. Make sure the simulator is running (info is written on startup)."
        )]

    try:
        with open(info_file, 'r') as f:
            info = json.load(f)

        lines = [
            "Solar2D Display Info:",
            "",
            f"Content Size: {info.get('contentWidth', '?')} x {info.get('contentHeight', '?')}",
            f"Actual Content Size: {info.get('actualContentWidth', '?')} x {info.get('actualContentHeight', '?')}",
            f"Screen Origin: ({info.get('screenOriginX', '?')}, {info.get('screenOriginY', '?')})",
            "",
            "Note: Screenshots are captured at content size.",
            "Tap coordinates should be in content space (0,0 is top-left of content area)."
        ]
        return [TextContent(type="text", text="\n".join(lines))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error reading display info: {str(e)}")]
