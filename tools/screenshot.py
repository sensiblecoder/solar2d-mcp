"""
Screenshot tools - Control screenshot recording and retrieve captured images.
"""

import asyncio
import base64
import os
import tempfile
from pathlib import Path

from mcp.types import Tool, TextContent, ImageContent

from utils import find_main_lua


# Tool definitions
START_RECORDING_TOOL = Tool(
    name="start_screenshot_recording",
    description="Start recording screenshots from the Solar2D simulator. Screenshots are captured every 100ms. Can be called while already recording to extend the duration.",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            },
            "duration": {
                "type": "number",
                "description": "Recording duration in seconds (default: 60, max: 300)",
                "default": 60
            }
        },
        "required": ["project_path"]
    }
)

STOP_RECORDING_TOOL = Tool(
    name="stop_screenshot_recording",
    description="Stop screenshot recording early.",
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

GET_SCREENSHOT_TOOL = Tool(
    name="get_simulator_screenshot",
    description="Get a screenshot from the Solar2D simulator for visual analysis. By default captures a fresh screenshot of the current simulator state. Use 'last' or a number to retrieve from a previous recording session.",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            },
            "which": {
                "type": "string",
                "description": "'latest' (default) = capture fresh screenshot now. 'last' = most recent from recording. 'all' = list recorded screenshots. Or a number like '5' for specific recorded screenshot.",
                "default": "latest"
            }
        },
        "required": ["project_path"]
    }
)

LIST_SCREENSHOTS_TOOL = Tool(
    name="list_screenshots",
    description="List all available screenshots from the Solar2D simulator.",
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
TOOLS = [START_RECORDING_TOOL, STOP_RECORDING_TOOL, GET_SCREENSHOT_TOOL, LIST_SCREENSHOTS_TOOL]


def _get_project_name(project_path: str) -> str:
    """Get the project name from the path."""
    main_lua_path = find_main_lua(project_path)
    project_dir = str(Path(main_lua_path).parent)
    return Path(project_dir).name


def _get_screenshot_dir(project_name: str) -> str:
    """Get the screenshot directory path."""
    return os.path.join(tempfile.gettempdir(), f"solar2d_screenshots_{project_name}")


def _get_control_file(project_name: str) -> str:
    """Get the control file path."""
    return os.path.join(tempfile.gettempdir(), f"solar2d_screenshots_{project_name}.control")


async def handle_start_recording(arguments: dict) -> list[TextContent]:
    """Start screenshot recording."""
    project_path = arguments.get("project_path")
    duration = arguments.get("duration", 60)

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    project_name = _get_project_name(project_path)
    control_file = _get_control_file(project_name)
    screenshot_dir = _get_screenshot_dir(project_name)

    # Cap duration at 5 minutes (300 seconds)
    duration = min(int(duration), 300)

    # Write duration to control file
    with open(control_file, 'w') as f:
        f.write(str(duration))

    return [TextContent(
        type="text",
        text=f"Screenshot recording started!\n\nDuration: {duration} seconds\nInterval: 100ms (10 fps)\nScreenshots will be saved to: {screenshot_dir}\n\nUse get_simulator_screenshot to view captured images.\nUse stop_screenshot_recording to stop early."
    )]


async def handle_stop_recording(arguments: dict) -> list[TextContent]:
    """Stop screenshot recording."""
    project_path = arguments.get("project_path")

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    project_name = _get_project_name(project_path)
    control_file = _get_control_file(project_name)

    # Write 0 to control file to stop recording
    with open(control_file, 'w') as f:
        f.write("0")

    return [TextContent(
        type="text",
        text="Screenshot recording stopped."
    )]


async def handle_get_screenshot(arguments: dict) -> list[TextContent | ImageContent]:
    """Get screenshot(s) from the simulator."""
    project_path = arguments.get("project_path")
    which = arguments.get("which", "latest")

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    project_name = _get_project_name(project_path)
    screenshot_dir = _get_screenshot_dir(project_name)
    control_file = _get_control_file(project_name)

    # Handle "latest" - capture fresh screenshot on demand
    if which == "latest":
        # Ensure screenshot dir exists
        os.makedirs(screenshot_dir, exist_ok=True)

        # Write "now" command to trigger immediate capture
        with open(control_file, 'w') as f:
            f.write("now")

        # Wait for the screenshot to be captured (polling interval is 500ms)
        latest_file = os.path.join(screenshot_dir, "screenshot_latest.jpg")
        # Get current mtime if file exists
        old_mtime = os.path.getmtime(latest_file) if os.path.exists(latest_file) else 0

        # Wait up to 2 seconds for new screenshot
        for _ in range(20):
            await asyncio.sleep(0.1)
            if os.path.exists(latest_file):
                new_mtime = os.path.getmtime(latest_file)
                if new_mtime > old_mtime:
                    # New screenshot captured
                    try:
                        with open(latest_file, 'rb') as f:
                            image_data = base64.standard_b64encode(f.read()).decode('utf-8')

                        return [
                            ImageContent(type="image", data=image_data, mimeType="image/jpeg")
                        ]
                    except Exception as e:
                        return [TextContent(type="text", text=f"Error reading screenshot: {str(e)}")]

        return [TextContent(
            type="text",
            text="Timeout waiting for screenshot. Make sure the simulator is running."
        )]

    if not os.path.exists(screenshot_dir):
        return [TextContent(
            type="text",
            text=f"Screenshot directory not found: {screenshot_dir}\n\nMake sure to run the project first with run_solar2d_project."
        )]

    # Get list of recorded screenshots (exclude screenshot_latest.jpg)
    screenshots = sorted([
        f for f in os.listdir(screenshot_dir)
        if f.startswith("screenshot_") and f.endswith(".jpg") and f != "screenshot_latest.jpg"
    ])

    # Handle "last" - get most recent from recording
    if which == "last":
        if not screenshots:
            return [TextContent(
                type="text",
                text="No recorded screenshots found. Use start_screenshot_recording to begin capturing."
            )]
        files_to_return = [screenshots[-1]]
    elif which == "all":
        # Return file list only (not images) to avoid 413 errors
        if not screenshots:
            return [TextContent(
                type="text",
                text="No recorded screenshots found. Use start_screenshot_recording to begin capturing."
            )]
        lines = [f"Found {len(screenshots)} screenshot(s):", ""]
        for filename in screenshots:
            filepath = os.path.join(screenshot_dir, filename)
            size = os.path.getsize(filepath)
            lines.append(f"  {filename} ({size:,} bytes)")
        lines.append("")
        lines.append("Use get_simulator_screenshot with a specific number to view an image.")
        return [TextContent(type="text", text="\n".join(lines))]
    else:
        # Try to get specific screenshot number
        try:
            num = int(which)
            filename = f"screenshot_{num:03d}.jpg"
            if filename in screenshots:
                files_to_return = [filename]
            else:
                if not screenshots:
                    return [TextContent(
                        type="text",
                        text="No recorded screenshots found. Use start_screenshot_recording to begin capturing."
                    )]
                return [TextContent(
                    type="text",
                    text=f"Screenshot {num} not found. Available: 1-{len(screenshots)}"
                )]
        except ValueError:
            return [TextContent(
                type="text",
                text=f"Invalid 'which' value: {which}. Use 'latest', 'last', 'all', or a number."
            )]

    # Return the images
    result = []
    for filename in files_to_return:
        filepath = os.path.join(screenshot_dir, filename)
        try:
            with open(filepath, 'rb') as f:
                image_data = base64.standard_b64encode(f.read()).decode('utf-8')

            result.append(ImageContent(
                type="image",
                data=image_data,
                mimeType="image/jpeg"
            ))
        except Exception as e:
            result.append(TextContent(
                type="text",
                text=f"Error reading {filename}: {str(e)}"
            ))

    # Add a text description
    if len(files_to_return) == 1:
        result.insert(0, TextContent(
            type="text",
            text=f"Screenshot: {files_to_return[0]}"
        ))
    else:
        result.insert(0, TextContent(
            type="text",
            text=f"Returning {len(files_to_return)} screenshots"
        ))

    return result


async def handle_list_screenshots(arguments: dict) -> list[TextContent]:
    """List available screenshots."""
    project_path = arguments.get("project_path")

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    project_name = _get_project_name(project_path)
    screenshot_dir = _get_screenshot_dir(project_name)

    if not os.path.exists(screenshot_dir):
        return [TextContent(
            type="text",
            text=f"Screenshot directory not found: {screenshot_dir}\n\nMake sure to run the project first with run_solar2d_project."
        )]

    # Get list of screenshots with file info
    screenshots = sorted([
        f for f in os.listdir(screenshot_dir)
        if f.startswith("screenshot_") and f.endswith(".jpg")
    ])

    if not screenshots:
        return [TextContent(
            type="text",
            text="No screenshots found. Use start_screenshot_recording to begin capturing."
        )]

    lines = [f"Found {len(screenshots)} screenshot(s) in {screenshot_dir}:", ""]
    for filename in screenshots:
        filepath = os.path.join(screenshot_dir, filename)
        size = os.path.getsize(filepath)
        lines.append(f"  {filename} ({size:,} bytes)")

    lines.append("")
    lines.append("Use get_simulator_screenshot to view images.")

    return [TextContent(type="text", text="\n".join(lines))]
