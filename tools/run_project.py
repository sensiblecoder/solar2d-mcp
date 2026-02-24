"""
run_solar2d_project tool - Run a Solar2D project in the simulator.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from mcp.types import Tool, TextContent

from utils import find_main_lua, running_projects
import config


TOOL = Tool(
    name="run_solar2d_project",
    description="Run a Solar2D project in the simulator. Provide either a path to main.lua or a project directory.",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            },
            "debug": {
                "type": "boolean",
                "description": "Enable debug mode (default: true)",
                "default": True
            },
            "no_console": {
                "type": "boolean",
                "description": "Disable console output (default: false to capture logs)",
                "default": False
            }
        },
        "required": ["project_path"]
    }
)


def create_logging_wrapper(project_dir: str, log_file: str) -> str:
    """Create a Lua file that redirects print() to a log file."""
    lua_logger = f'''
-- MCP Logger: Redirects print() to file for MCP server access
local mcp_log_file = "{log_file}"
local original_print = print

-- Truncate log file on simulator start (clear old logs)
do
    local file = io.open(mcp_log_file, "w")
    if file then
        file:write("=== Solar2D Simulator Started ===\\n")
        file:close()
    end
end

_G.print = function(...)
    local args = {{...}}
    local message = ""
    for i, v in ipairs(args) do
        if i > 1 then message = message .. "\\t" end
        message = message .. tostring(v)
    end

    -- Call original print
    original_print(...)

    -- Also write to MCP log file (append mode)
    local file = io.open(mcp_log_file, "a")
    if file then
        file:write(message .. "\\n")
        file:flush()
        file:close()
    end
end

print("[MCP] Logging initialized - output will be captured for Claude")
'''

    logger_path = os.path.join(project_dir, "_mcp_logger.lua")
    with open(logger_path, 'w') as f:
        f.write(lua_logger)

    return logger_path


def create_screenshot_module(project_dir: str, project_name: str) -> str:
    """Create a Lua file that captures screenshots on demand."""
    screenshot_dir = os.path.join(tempfile.gettempdir(), f"solar2d_screenshots_{project_name}")
    control_file = os.path.join(tempfile.gettempdir(), f"solar2d_screenshots_{project_name}.control")

    lua_screenshot = f'''
-- MCP Screenshot: Captures screenshots periodically when recording is enabled
local lfs = require("lfs")
local screenshotDir = "{screenshot_dir}"
local controlFile = "{control_file}"
local captureInterval = 100  -- 100ms between captures
local screenshotCount = 0
local recordingEndTime = 0

-- Helper to check if file exists
local function fileExists(path)
    local file = io.open(path, "r")
    if file then
        file:close()
        return true
    end
    return false
end

-- Helper to read and consume control file
local function readControlFile()
    local file = io.open(controlFile, "r")
    if file then
        local content = file:read("*all")
        file:close()
        os.remove(controlFile)  -- Consume the command
        return content
    end
    return nil
end

-- Clear screenshot directory on start
local function clearScreenshotDir()
    -- Create directory if it doesn't exist
    lfs.mkdir(screenshotDir)
    -- Remove existing screenshots
    for file in lfs.dir(screenshotDir) do
        if file ~= "." and file ~= ".." then
            os.remove(screenshotDir .. "/" .. file)
        end
    end
end

-- Check if currently recording
local function isRecording()
    return system.getTimer() < recordingEndTime
end

-- Helper to copy file (works across volumes)
local function copyFile(src, dst)
    local infile = io.open(src, "rb")
    if not infile then return false end
    local content = infile:read("*all")
    infile:close()

    local outfile = io.open(dst, "wb")
    if not outfile then return false end
    outfile:write(content)
    outfile:close()
    return true
end

-- Capture screenshot
local function captureScreen()
    if not isRecording() then return end

    screenshotCount = screenshotCount + 1
    local filename = string.format("screenshot_%03d.jpg", screenshotCount)
    local fullPath = screenshotDir .. "/" .. filename

    -- Capture the display to Solar2D's temp directory
    display.save(display.currentStage, {{
        filename = filename,
        baseDir = system.TemporaryDirectory,
        captureOffscreenArea = false,
        isFullResolution = false
    }})

    -- Copy from Solar2D temp to our /tmp/ screenshot directory
    local tempPath = system.pathForFile(filename, system.TemporaryDirectory)
    if tempPath then
        if copyFile(tempPath, fullPath) then
            os.remove(tempPath)  -- Clean up temp file
        end
    end
end

-- Capture a single on-demand screenshot (not part of recording sequence)
local function captureOnDemand()
    local filename = "screenshot_latest.jpg"
    local fullPath = screenshotDir .. "/" .. filename

    -- Capture the display to Solar2D's temp directory
    display.save(display.currentStage, {{
        filename = filename,
        baseDir = system.TemporaryDirectory,
        captureOffscreenArea = false,
        isFullResolution = false
    }})

    -- Copy from Solar2D temp to our /tmp/ screenshot directory
    local tempPath = system.pathForFile(filename, system.TemporaryDirectory)
    if tempPath then
        if copyFile(tempPath, fullPath) then
            os.remove(tempPath)  -- Clean up temp file
            print("[MCP Screenshot] On-demand capture saved")
        end
    end
end

-- Check control file for recording commands
local function checkControl()
    local content = readControlFile()
    if not content then return end

    -- Check for "now" command (on-demand capture)
    if content == "now" then
        captureOnDemand()
        return
    end

    local duration = tonumber(content)
    if duration == nil then
        -- Not a number, ignore
        return
    elseif duration > 0 then
        recordingEndTime = system.getTimer() + (duration * 1000)
        print("[MCP Screenshot] Recording for " .. duration .. " seconds (screenshots continue from #" .. (screenshotCount + 1) .. ")")
    elseif duration == 0 then
        -- Explicit stop command
        recordingEndTime = 0
        print("[MCP Screenshot] Recording stopped at screenshot #" .. screenshotCount)
    end
end

-- Initialize
clearScreenshotDir()
print("[MCP Screenshot] Module initialized - screenshots will be saved to: " .. screenshotDir)

-- Start timers
timer.performWithDelay(captureInterval, captureScreen, 0)
timer.performWithDelay(500, checkControl, 0)
'''

    screenshot_path = os.path.join(project_dir, "_mcp_screenshot.lua")
    with open(screenshot_path, 'w') as f:
        f.write(lua_screenshot)

    return screenshot_path


def create_touch_module(project_dir: str, project_name: str) -> str:
    """Create a Lua file that handles touch simulation via control file."""
    control_file = os.path.join(tempfile.gettempdir(), f"solar2d_touch_{project_name}.control")
    info_file = os.path.join(tempfile.gettempdir(), f"solar2d_display_{project_name}.json")

    lua_touch = f'''
-- MCP Touch: Simulates touch events from control file commands
local controlFile = "{control_file}"
local infoFile = "{info_file}"
local checkInterval = 100  -- Check for commands every 100ms
local json = require("json")

-- Stored target from "began" phase for consistent event dispatch
local touchTarget = nil
local touchStartX, touchStartY = 0, 0

-- Helper to read and consume control file
local function readControlFile()
    local file = io.open(controlFile, "r")
    if file then
        local content = file:read("*all")
        file:close()
        os.remove(controlFile)  -- Consume the command
        return content
    end
    return nil
end

-- Parse command string
local function parseCommand(content)
    local parts = {{}}
    for part in string.gmatch(content, "[^,]+") do
        table.insert(parts, part)
    end
    return parts
end

-- Check if object has a touch listener
local function hasTouchListener(obj)
    -- Check for touch_handler (used by some frameworks)
    if obj.touch_handler then return true end
    -- Check for _tableListeners.touch (standard Solar2D listener table)
    if obj._tableListeners and obj._tableListeners.touch then return true end
    -- Check for _functionListeners.touch
    if obj._functionListeners and obj._functionListeners.touch then return true end
    return false
end

-- Find the topmost touchable object at coordinates via hit testing
local function findHitObject(group, x, y)
    if not group or not group.numChildren then return nil end

    -- Traverse in reverse order (higher index = on top)
    for i = group.numChildren, 1, -1 do
        local child = group[i]
        if child and child.isVisible ~= false then
            -- Recurse into groups first
            if child.numChildren then
                local hit = findHitObject(child, x, y)
                if hit then return hit end
            end

            -- Check if this object is within bounds
            if child.contentBounds then
                local bounds = child.contentBounds
                if x >= bounds.xMin and x <= bounds.xMax and
                   y >= bounds.yMin and y <= bounds.yMax then
                    -- Check if it has a touch listener
                    if hasTouchListener(child) then
                        return child
                    end
                end
            end
        end
    end
    return nil
end

-- Dispatch a touch event to appropriate target
local function dispatchTouch(phase, x, y)
    local target = nil

    if phase == "began" then
        -- Find the topmost touchable object at this point
        target = findHitObject(display.getCurrentStage(), x, y)
        if target then
            touchTarget = target
            touchStartX, touchStartY = x, y
        end
    else
        target = touchTarget
        if phase == "ended" then
            touchTarget = nil
        end
    end

    local event = {{
        name = "touch",
        phase = phase,
        x = x,
        y = y,
        xStart = touchStartX or x,
        yStart = touchStartY or y,
        time = system.getTimer(),
        target = target
    }}

    if target then
        target:dispatchEvent(event)
    else
        -- Fallback to Runtime if no target found
        Runtime:dispatchEvent(event)
    end
end

-- Write display info to file
local function writeDisplayInfo()
    local info = {{
        contentWidth = display.contentWidth,
        contentHeight = display.contentHeight,
        actualContentWidth = display.actualContentWidth,
        actualContentHeight = display.actualContentHeight,
        screenOriginX = display.screenOriginX,
        screenOriginY = display.screenOriginY
    }}

    local file = io.open(infoFile, "w")
    if file then
        file:write(json.encode(info))
        file:close()
    end
end

-- Execute a tap at coordinates
local function executeTap(x, y)
    print("[MCP Touch] Tap at (" .. x .. ", " .. y .. ")")

    -- Dispatch "began" phase
    dispatchTouch("began", x, y)

    -- Short delay, then dispatch "ended" phase
    timer.performWithDelay(50, function()
        dispatchTouch("ended", x, y)
    end)
end

-- Execute a drag from (x1,y1) to (x2,y2) over duration ms
local function executeDrag(x1, y1, x2, y2, duration)
    print("[MCP Touch] Drag from (" .. x1 .. ", " .. y1 .. ") to (" .. x2 .. ", " .. y2 .. ") over " .. duration .. "ms")

    local steps = math.max(1, math.floor(duration / 16))  -- ~60fps
    local stepDelay = duration / steps

    -- Dispatch "began" at start position
    dispatchTouch("began", x1, y1)

    -- Dispatch "moved" events at interpolated positions
    for i = 1, steps do
        timer.performWithDelay(math.floor(stepDelay * i), function()
            local t = i / steps
            local x = x1 + (x2 - x1) * t
            local y = y1 + (y2 - y1) * t
            dispatchTouch("moved", x, y)

            -- Dispatch "ended" after the final moved event
            if i == steps then
                timer.performWithDelay(16, function()
                    dispatchTouch("ended", x2, y2)
                end)
            end
        end)
    end
end

-- Check control file for commands
local function checkControl()
    local content = readControlFile()
    if content then
        local parts = parseCommand(content)
        local cmd = parts[1]

        if cmd == "tap" then
            local x = tonumber(parts[2])
            local y = tonumber(parts[3])
            if x and y then
                executeTap(x, y)
            else
                print("[MCP Touch] Invalid tap coordinates")
            end
        elseif cmd == "drag" then
            local x1 = tonumber(parts[2])
            local y1 = tonumber(parts[3])
            local x2 = tonumber(parts[4])
            local y2 = tonumber(parts[5])
            local dur = tonumber(parts[6])
            if x1 and y1 and x2 and y2 and dur then
                executeDrag(x1, y1, x2, y2, dur)
            else
                print("[MCP Touch] Invalid drag parameters")
            end
        else
            print("[MCP Touch] Unknown command: " .. tostring(cmd))
        end
    end
end

-- Initialize
writeDisplayInfo()  -- Write display info on startup
print("[MCP Touch] Module initialized - listening for touch commands")

-- Start polling for commands
timer.performWithDelay(checkInterval, checkControl, 0)
'''

    touch_path = os.path.join(project_dir, "_mcp_touch.lua")
    with open(touch_path, 'w') as f:
        f.write(lua_touch)

    return touch_path


def inject_module_into_main_lua(main_lua_path: str, module_name: str) -> bool:
    """Inject a require statement into main.lua if not already present."""
    try:
        with open(main_lua_path, 'r') as f:
            content = f.read()

        require_str = f'require("{module_name}")'
        require_str_single = f"require('{module_name}')"

        # Check if already injected
        if require_str in content or require_str_single in content:
            return False  # Already present

        lines = content.split('\n')

        # Find the best insertion point
        # Look for mobdebug line, or first require, or beginning
        insert_index = 0

        for i, line in enumerate(lines):
            # Insert after mobdebug if present
            if 'mobdebug' in line.lower() and 'require' in line:
                insert_index = i + 1
                break
            # Otherwise, insert before first require that's not a comment
            elif 'require' in line and not line.strip().startswith('--'):
                insert_index = i
                break

        # If no requires found, insert after initial comments/blank lines
        if insert_index == 0:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith('--'):
                    insert_index = i
                    break

        # Insert the require line
        lines.insert(insert_index, f'{require_str}  -- Auto-injected by MCP server')

        # Write back to file
        with open(main_lua_path, 'w') as f:
            f.write('\n'.join(lines))

        return True  # Successfully injected

    except Exception as e:
        # If we can't modify the file, just return False
        return False


def inject_logger_into_main_lua(main_lua_path: str) -> bool:
    """Inject require("_mcp_logger") into main.lua if not already present."""
    try:
        with open(main_lua_path, 'r') as f:
            content = f.read()

        # Check if already injected
        if 'require("_mcp_logger")' in content or "require('_mcp_logger')" in content:
            return False  # Already present

        lines = content.split('\n')

        # Find the best insertion point
        # Look for mobdebug line, or first require, or beginning
        insert_index = 0

        for i, line in enumerate(lines):
            # Insert after mobdebug if present
            if 'mobdebug' in line.lower() and 'require' in line:
                insert_index = i + 1
                break
            # Otherwise, insert before first require that's not a comment
            elif 'require' in line and not line.strip().startswith('--'):
                insert_index = i
                break

        # If no requires found, insert after initial comments/blank lines
        if insert_index == 0:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith('--'):
                    insert_index = i
                    break

        # Insert the require line
        lines.insert(insert_index, 'require("_mcp_logger")  -- Auto-injected by MCP server for log capture')

        # Write back to file
        with open(main_lua_path, 'w') as f:
            f.write('\n'.join(lines))

        return True  # Successfully injected

    except Exception as e:
        # If we can't modify the file, just return False
        return False


async def handle(arguments: dict) -> list[TextContent]:
    """Handle run_solar2d_project tool call."""
    project_path = arguments.get("project_path")
    debug = arguments.get("debug", True)
    no_console = arguments.get("no_console", False)

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    # Check if Solar2D is configured
    simulator_path, detected_paths, needs_confirmation = config.get_simulator_or_detect()

    if needs_confirmation:
        # Prompt user to configure first
        lines = ["Solar2D simulator needs to be configured before running projects.", ""]

        if detected_paths:
            lines.append("Detected simulators:")
            for path in detected_paths:
                lines.append(f"  - {path}")
            lines.append("")
            lines.append("Please use the configure_solar2d tool to confirm or select a simulator:")
            lines.append("  - Call configure_solar2d with confirm=true to use the detected path")
            lines.append("  - Or provide a specific path with simulator_path=\"...\"")
        else:
            lines.append("No Solar2D simulators were detected.")
            lines.append("Please use the configure_solar2d tool to set the simulator path:")
            lines.append("  configure_solar2d(simulator_path=\"/path/to/Corona Simulator\")")

        return [TextContent(type="text", text="\n".join(lines))]

    if not simulator_path or not os.path.exists(simulator_path):
        return [TextContent(
            type="text",
            text=f"Error: Solar2D Simulator not found. Please run configure_solar2d to set the path."
        )]

    # Find main.lua
    main_lua_path = find_main_lua(project_path)
    project_dir = str(Path(main_lua_path).parent)

    # Close any existing simulator for this project
    if project_dir in running_projects:
        old_process = running_projects[project_dir]["process"]
        if old_process.poll() is None:  # Still running
            old_process.terminate()
            try:
                old_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                old_process.kill()
        del running_projects[project_dir]

    # Check if main.lua exists
    if not os.path.exists(main_lua_path):
        return [TextContent(
            type="text",
            text=f"Error: main.lua not found at {main_lua_path}"
        )]

    # Create log file with project-based name (not timestamp) for predictable location
    project_name = Path(project_dir).name
    log_file = os.path.join(tempfile.gettempdir(), f"corona_log_{project_name}.txt")

    # Create Lua logging wrapper
    logger_path = create_logging_wrapper(project_dir, log_file)

    # Create screenshot module
    screenshot_path = create_screenshot_module(project_dir, project_name)

    # Create touch module
    touch_path = create_touch_module(project_dir, project_name)

    # Inject modules into main.lua if not already present
    logger_injected = inject_module_into_main_lua(main_lua_path, "_mcp_logger")
    screenshot_injected = inject_module_into_main_lua(main_lua_path, "_mcp_screenshot")
    touch_injected = inject_module_into_main_lua(main_lua_path, "_mcp_touch")

    # Build the command
    cmd = [simulator_path]

    if no_console:
        cmd.extend(["-no-console", "YES"])

    if debug:
        cmd.extend(["-debug", "1"])

    cmd.extend(["-project", main_lua_path])

    try:
        # Run the simulator (non-blocking)
        # Don't capture stdout/stderr - let _mcp_logger.lua handle all logging
        process = subprocess.Popen(
            cmd,
            start_new_session=True
        )

        # Track the running project
        running_projects[project_dir] = {
            "pid": process.pid,
            "log_file": log_file,
            "process": process,
            "main_lua": main_lua_path
        }

        # Build status messages
        status_lines = []
        if logger_injected:
            status_lines.append("Logger injected into main.lua")
        else:
            status_lines.append("Logger already present in main.lua")

        if screenshot_injected:
            status_lines.append("Screenshot module injected into main.lua")
        else:
            status_lines.append("Screenshot module already present in main.lua")

        if touch_injected:
            status_lines.append("Touch module injected into main.lua")
        else:
            status_lines.append("Touch module already present in main.lua")

        screenshot_dir = os.path.join(tempfile.gettempdir(), f"solar2d_screenshots_{project_name}")

        return [TextContent(
            type="text",
            text=f"Solar2D Simulator launched successfully!\n\nProject: {main_lua_path}\nPID: {process.pid}\nLog file: {log_file}\nScreenshot dir: {screenshot_dir}\nDebug: {debug}\nNo Console: {no_console}\n\n{chr(10).join(status_lines)}\n\nAll print() output will be captured automatically.\nUse read_solar2d_logs to view the console output.\nUse start_screenshot_recording to capture screenshots."
        )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=f"Error launching Solar2D Simulator: {str(e)}"
        )]
