#!/usr/bin/env python3
"""
Solar2D MCP Server
A Model Context Protocol server for working with Solar2D (Corona SDK) projects.
"""

import asyncio
import subprocess
import os
import tempfile
from pathlib import Path
from mcp.server import Server
from mcp.types import Tool, TextContent, Resource, EmbeddedResource
from mcp.server.stdio import stdio_server

# Initialize the MCP server
app = Server("solar2d-server")

# Corona Simulator path
CORONA_SIMULATOR = "/Applications/Corona-3726/Corona Simulator.app/Contents/MacOS/Corona Simulator"

# Track running Corona processes and their log files
running_projects = {}  # {project_path: {"pid": int, "log_file": str, "process": subprocess.Popen}}


def find_main_lua(project_path: str) -> str:
    """Find main.lua in the given project path."""
    path = Path(project_path)

    # If the path is already main.lua
    if path.name == "main.lua" and path.exists():
        return str(path.absolute())

    # If the path is a directory, look for main.lua inside
    if path.is_dir():
        main_lua = path / "main.lua"
        if main_lua.exists():
            return str(main_lua.absolute())

    # If neither works, return the original path (will error later)
    return str(Path(project_path).absolute())


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


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools for Solar2D projects."""
    return [
        Tool(
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
        ),
        Tool(
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
        ),
        Tool(
            name="list_running_projects",
            description="List all currently running Solar2D Simulator projects tracked by this server.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    if name == "run_solar2d_project":
        project_path = arguments.get("project_path")
        debug = arguments.get("debug", True)
        no_console = arguments.get("no_console", False)

        if not project_path:
            return [TextContent(type="text", text="Error: project_path is required")]

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

        # Check if Solar2D Simulator exists
        if not os.path.exists(CORONA_SIMULATOR):
            return [TextContent(
                type="text",
                text=f"Error: Solar2D Simulator not found at {CORONA_SIMULATOR}"
            )]

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

        # Inject logger into main.lua if not already present
        injected = inject_logger_into_main_lua(main_lua_path)

        # Build the command
        cmd = [CORONA_SIMULATOR]

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

            logger_status = "Logger injected into main.lua" if injected else "Logger already present in main.lua"

            return [TextContent(
                type="text",
                text=f"Solar2D Simulator launched successfully!\n\nProject: {main_lua_path}\nPID: {process.pid}\nLog file: {log_file}\nDebug: {debug}\nNo Console: {no_console}\n\n{logger_status}\n\nAll print() output will be captured automatically.\nUse read_solar2d_logs to view the console output."
            )]

        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error launching Solar2D Simulator: {str(e)}"
            )]

    elif name == "read_solar2d_logs":
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

    elif name == "list_running_projects":
        if not running_projects:
            return [TextContent(
                type="text",
                text="No Solar2D Simulator projects are currently running."
            )]

        projects_info = []
        for project_dir, info in running_projects.items():
            # Check if process is still running
            process = info["process"]
            status = "running" if process.poll() is None else "stopped"

            projects_info.append(
                f"Project: {project_dir}\n"
                f"  Main: {info['main_lua']}\n"
                f"  PID: {info['pid']}\n"
                f"  Status: {status}\n"
                f"  Log: {info['log_file']}"
            )

        return [TextContent(
            type="text",
            text="Running Solar2D Projects:\n\n" + "\n\n".join(projects_info)
        )]

    raise ValueError(f"Unknown tool: {name}")


@app.list_resources()
async def list_resources() -> list[Resource]:
    """List available resources."""
    return [
        Resource(
            uri="solar2d://info",
            name="Solar2D Server Info",
            mimeType="text/plain",
            description="Information about this Solar2D MCP server"
        )
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """Read a resource by URI."""
    if uri == "solar2d://info":
        return """Solar2D MCP Server v0.1.0

This is a Model Context Protocol server for working with Solar2D (Corona SDK) projects.

Capabilities:
- Project analysis
- Code context extraction
- Build configuration help
- API reference

Status: Hello World Implementation
"""

    raise ValueError(f"Unknown resource: {uri}")


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
