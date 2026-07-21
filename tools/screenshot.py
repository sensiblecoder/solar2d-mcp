"""
Screenshot tools - Control screenshot recording and retrieve captured images.
"""

import asyncio
import base64
import os
import shutil
import tempfile
from pathlib import Path

from mcp.types import ImageContent, TextContent, Tool

from utils import find_main_lua

# Hard ceiling on a single recording, mirrored in the injected capture loop
# (run_project.py: MAX_RECORDING_SECONDS). The Lua loop enforces it too, so a
# runaway recording self-terminates even if 'stop' is never sent.
MAX_RECORDING_SECONDS = 300

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

ENCODE_VIDEO_TOOL = Tool(
    name="encode_recording_video",
    description="Stitch the frames from a screenshot-recording session into an MP4 video and return its file path. Workflow: start_screenshot_recording -> drive the sim (simulate_tap / run a test / play) -> stop_screenshot_recording -> encode_recording_video. Frames are the recorder's screenshot_NNN.jpg (10fps). Prefer MP4 for anything the user watches remotely: it plays inline in the Claude app (a GIF does NOT) and is ~3x smaller. Requires ffmpeg on the host. Returns the output path to hand to SendUserFile (display: render).",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            },
            "fps": {
                "type": "number",
                "description": "Output frame rate. The recorder captures at 10fps, so 10 is real-time; lower slows the clip down. (default: 10)",
                "default": 10
            },
            "width": {
                "type": "number",
                "description": "Output width in pixels (height auto, keeps aspect). 0 = keep native capture size. (default: 560)",
                "default": 560
            },
            "start_frame": {
                "type": "number",
                "description": "First frame number to include (default: first available). Use with 'all' listing / get_simulator_screenshot to pick a window."
            },
            "end_frame": {
                "type": "number",
                "description": "Last frame number to include (default: last available)."
            },
            "filename": {
                "type": "string",
                "description": "Output file name (\".mp4\" appended if missing). Written to a 'video/' subdir of the screenshot dir. (default: recording.mp4)",
                "default": "recording.mp4"
            }
        },
        "required": ["project_path"]
    }
)

# Export all tools
TOOLS = [START_RECORDING_TOOL, STOP_RECORDING_TOOL, GET_SCREENSHOT_TOOL, LIST_SCREENSHOTS_TOOL, ENCODE_VIDEO_TOOL]


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


def _find_ffmpeg() -> str | None:
    """Locate the ffmpeg binary on PATH, or in the usual Homebrew/system spots."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.path.exists(candidate):
            return candidate
    return None


async def handle_start_recording(arguments: dict) -> list[TextContent]:
    """Start screenshot recording."""
    project_path = arguments.get("project_path")
    duration = arguments.get("duration", 60)

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    project_name = _get_project_name(project_path)
    control_file = _get_control_file(project_name)
    screenshot_dir = _get_screenshot_dir(project_name)

    # Cap duration at the hard ceiling (the Lua loop enforces it too).
    duration = min(int(duration), MAX_RECORDING_SECONDS)

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


async def handle_encode_video(arguments: dict) -> list[TextContent]:
    """Encode recorded frames into an MP4 and return its path."""
    project_path = arguments.get("project_path")
    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    fps = max(1, int(arguments.get("fps", 10)))
    width = int(arguments.get("width", 560))
    filename = str(arguments.get("filename", "recording.mp4"))
    if not filename.lower().endswith(".mp4"):
        filename += ".mp4"

    project_name = _get_project_name(project_path)
    screenshot_dir = _get_screenshot_dir(project_name)
    if not os.path.exists(screenshot_dir):
        return [TextContent(
            type="text",
            text=f"Screenshot directory not found: {screenshot_dir}\n\nRecord first with start_screenshot_recording."
        )]

    # Frame numbers present (the recorder writes them contiguously as screenshot_NNN.jpg).
    nums = []
    for f in os.listdir(screenshot_dir):
        if f.startswith("screenshot_") and f.endswith(".jpg") and f != "screenshot_latest.jpg":
            try:
                nums.append(int(f[len("screenshot_"):-len(".jpg")]))
            except ValueError:
                pass
    if not nums:
        return [TextContent(
            type="text",
            text="No recorded frames found. Use start_screenshot_recording, drive the sim, then stop_screenshot_recording before encoding."
        )]
    nums.sort()
    first_available, last_available = nums[0], nums[-1]

    start = int(arguments.get("start_frame", first_available))
    end = int(arguments.get("end_frame", last_available))
    start = max(start, first_available)
    end = min(end, last_available)
    if end < start:
        return [TextContent(
            type="text",
            text=f"Empty frame range: start {start} > end {end} (available {first_available}-{last_available})."
        )]
    count = end - start + 1

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return [TextContent(
            type="text",
            text="ffmpeg not found (checked PATH and Homebrew/system paths). Install it: brew install ffmpeg."
        )]

    video_dir = os.path.join(screenshot_dir, "video")
    os.makedirs(video_dir, exist_ok=True)
    out_path = os.path.join(video_dir, filename)

    # Even-dimension scale + yuv420p + faststart = broad inline playback (incl. the Claude app).
    scale = f"scale={width}:-2:flags=lanczos," if width and width > 0 else ""
    vf = f"{scale}format=yuv420p"
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-framerate", str(fps),
        "-start_number", str(start),
        "-i", os.path.join(screenshot_dir, "screenshot_%03d.jpg"),
        "-frames:v", str(count),
        "-vf", vf,
        "-r", str(fps),
        "-movflags", "+faststart",
        out_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not os.path.exists(out_path):
        return [TextContent(
            type="text",
            text=f"ffmpeg failed (exit {proc.returncode}):\n{stderr.decode(errors='replace')[:1500]}"
        )]

    size = os.path.getsize(out_path)
    seconds = count / fps
    return [TextContent(type="text", text=(
        f"Encoded {count} frame(s) [{start}-{end}] into MP4.\n"
        f"Path: {out_path}\n"
        f"~{seconds:.1f}s @ {fps}fps, {size:,} bytes\n\n"
        "Deliver it inline with SendUserFile (display: render) — MP4 plays in the Claude app; GIF does not."
    ))]


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
