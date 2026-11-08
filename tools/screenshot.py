"""
Screenshot tool - grab a still of the simulator, live or from a video recording.

Video recording lives in tools/video.py (ScreenCaptureKit, 60fps, with audio);
this module only does single frames.
"""

import asyncio
import base64
import os
import tempfile
from pathlib import Path

from mcp.types import ImageContent, TextContent, Tool

from utils import find_main_lua

GET_SCREENSHOT_TOOL = Tool(
    name="get_simulator_screenshot",
    description="Get a screenshot from the Solar2D simulator for visual analysis. By default captures a fresh screenshot of the current simulator state. Pass video_time to pull a full-resolution still out of a video recording instead (start_video_recording) — the way to get a crisp frame of a moment that is over.",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            },
            "video_time": {
                "type": "number",
                "description": "Seconds into a recording to grab the still from. Omit for a fresh live capture."
            },
            "recording": {
                "type": "string",
                "description": "With video_time: recording name or video path (default: the most recent recording)."
            },
            "save_to": {
                "type": "string",
                "description": "With video_time: also write the full-resolution PNG to this path (the returned image is downscaled)."
            }
        },
        "required": ["project_path"]
    }
)

TOOLS = [GET_SCREENSHOT_TOOL]


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


async def _still_from_video(arguments: dict, project_name: str) -> list[TextContent | ImageContent]:
    """Extract one frame from a recording: full-res PNG to save_to, a 1600px JPEG back to the caller."""
    from tools import video

    src = video._resolve_recording(project_name, arguments.get("recording"))
    if not src:
        return [TextContent(type="text", text="No recording found. Record with start_video_recording first.")]
    ffmpeg = video._find_tool("ffmpeg")
    if not ffmpeg:
        return [TextContent(type="text", text="ffmpeg not found. Install it: brew install ffmpeg.")]
    t = max(float(arguments["video_time"]), 0)
    preview = os.path.join(tempfile.gettempdir(), f"solar2d_still_{project_name}.jpg")
    save_to = arguments.get("save_to")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(src)]
    if save_to:
        cmd += ["-frames:v", "1", save_to]
    cmd += ["-frames:v", "1", "-vf", "scale=1600:-2", "-q:v", "3", preview]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0 or not os.path.exists(preview):
        return [TextContent(type="text", text=f"ffmpeg failed: {err.decode(errors='replace')[-800:]}")]
    with open(preview, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    note = f"Still at {t:.2f}s of {src.name}" + (f"; full resolution saved to {save_to}" if save_to else "")
    return [TextContent(type="text", text=note), ImageContent(type="image", data=data, mimeType="image/jpeg")]


async def handle_get_screenshot(arguments: dict) -> list[TextContent | ImageContent]:
    """Get screenshot(s) from the simulator."""
    project_path = arguments.get("project_path")

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    project_name = _get_project_name(project_path)
    screenshot_dir = _get_screenshot_dir(project_name)
    control_file = _get_control_file(project_name)

    if arguments.get("video_time") is not None:
        return await _still_from_video(arguments, project_name)

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
