# Solar2D MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for working with Solar2D (Corona SDK) projects. This server enables AI assistants to run, debug, and interact with Solar2D games.

**Works with any MCP-compatible client**, including:
- Claude Code CLI
- Other AI assistants that support MCP
- Custom integrations

## Setup

1. **Install dependencies:**
   ```bash
   pip install -e .
   ```

2. **Test the server:**
   ```bash
   python server.py
   ```

## Configuration

### Claude Desktop

Add this configuration to your Claude Desktop config file:

**MacOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows:** `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "solar2d": {
      "command": "/path/to/solar2d-mcp/.venv/bin/python",
      "args": [
        "/path/to/solar2d-mcp/server.py"
      ]
    }
  }
}
```

After adding the configuration, restart Claude Desktop.

### Claude Code CLI

Add the server using the `claude mcp add` command:

```bash
claude mcp add --scope user --transport stdio solar2d \
  /path/to/solar2d-mcp/.venv/bin/python \
  /path/to/solar2d-mcp/server.py
```

Verify the server is connected:

```bash
claude mcp list
```

You can also add it to a specific project using `--scope project` or create a `.mcp.json` file in your project root.

## First-Time Setup

On first use, the server needs to know where your Solar2D Simulator is installed.

1. **Auto-detection**: The server automatically scans common installation paths
2. **Confirmation**: You'll be prompted to confirm or provide the simulator location
3. **Remembered**: Your choice is saved to `~/.config/solar2d-mcp/config.json`

Example first-run flow:
```
User: Run my Solar2D project
Assistant: Solar2D simulator needs to be configured. Detected:
  - /Applications/Corona-3726/Corona Simulator.app/Contents/MacOS/Corona Simulator

Use configure_solar2d with confirm=true to use this path.

User: Yes, use that one
Assistant: [calls configure_solar2d(confirm=true)]
✓ Solar2D simulator confirmed and saved!
```

## Features

### Tools

- `configure_solar2d` - Configure the Solar2D simulator path
  - Auto-detects installed simulators
  - Persists configuration across sessions
  - Use `confirm=true` to accept detected path
  - Or provide custom path with `simulator_path="..."`
- `run_solar2d_project` - Run a Solar2D project in the simulator
  - Accepts project directory or main.lua path
  - Optional debug and console flags
  - Launches simulator in background
  - Injects logger that captures all print() output
- `read_solar2d_logs` - Read console logs from running Solar2D Simulator
  - View all Lua print() statements from your game code
  - Configurable number of recent lines to display
  - Helps debug your Lua code in real-time
  - **Automatic setup**: Logger is auto-injected into main.lua on first run
  - Note: Only captures Lua print() output, not Solar2D system messages
- `list_running_projects` - List all tracked Solar2D Simulator instances
  - Shows PID, status, and log file location
  - Useful for managing multiple running projects
- `start_screenshot_recording` - Start capturing screenshots from the simulator
  - Captures at 1 screenshot per second
  - Default recording duration: 60 seconds
  - Can extend recording while already capturing
- `stop_screenshot_recording` - Stop screenshot recording early
- `get_simulator_screenshot` - Get screenshot(s) for visual analysis
  - `which="latest"` - Get most recent screenshot (default)
  - `which="all"` - List all available screenshots
  - `which="5"` - Get specific screenshot by number
- `list_screenshots` - List all available screenshots with file sizes

### Resources

- `solar2d://info` - Server information

### Possible Plans

- ~~Ability to "see" the simulator~~ ✓ Implemented via screenshot recording!
  - Ability to "watch" a manual play-through
  - Ability to "find" things it can "see"
- Basic ability to click and swipe things it "sees"
  - More complex ability to "play", based on "watching"
- Built-in Skills
  - Conventions & Good Practices
  - Common Patterns / Templates

## Development

The server uses the Model Context Protocol (MCP) Python SDK.

### Project Structure

```
solar2d-mcp/
├── server.py          # MCP server entry point
├── config.py          # Configuration management and auto-detection
├── utils.py           # Shared utilities
├── tools/
│   ├── __init__.py    # Tool dispatcher
│   ├── configure.py   # configure_solar2d tool
│   ├── run_project.py # run_solar2d_project tool
│   ├── read_logs.py   # read_solar2d_logs tool
│   ├── list_projects.py # list_running_projects tool
│   └── screenshot.py  # Screenshot recording tools
├── resources/
│   ├── __init__.py    # Resource dispatcher
│   └── info.py        # solar2d://info resource
├── pyproject.toml     # Project dependencies and metadata
└── README.md          # This file
```

## Testing

Once configured, you can test the server with prompts like:

- "Configure Solar2D" (first-time setup)
- "Run my Solar2D project at /path/to/my-game"
- "Launch the Solar2D simulator with debug enabled for my project"
- "Show me the logs from my running Solar2D project"
- "Read the last 100 lines of Solar2D logs"
- "List all running Solar2D projects"

## Capturing Lua print() Output

The MCP server **automatically** captures all your Lua `print()` statements!

### Setup (One-time)

Run your project once through MCP:
1. The server creates a `_mcp_logger.lua` file in your project directory
2. **Automatically injects** `require("_mcp_logger")` into your `main.lua` (if not already present)

The logger is inserted intelligently:
- After `mobdebug` if present
- Before other `require` statements if no mobdebug
- At the start of the file otherwise

### Works with Manual Launches!

Once the logger is injected, it works **forever** - even when you launch Solar2D manually from your IDE or command line!

- Log file location: `/tmp/corona_log_<project-name>.txt` (predictable, based on project directory name)
- All Lua `print()` output is captured automatically by `_mcp_logger.lua`
- Your prints still display normally in the console (Solar2D's output)
- **Log file is cleared on each launch** - `_mcp_logger.lua` truncates the file when Solar2D starts
- Use `read_solar2d_logs` tool to view logs anytime, regardless of how Solar2D was launched
- The MCP server only reads the log file - `_mcp_logger.lua` is responsible for all writing

## Capturing Screenshots

The MCP server can capture screenshots from the running simulator for visual analysis!

### How It Works

1. **Auto-injected module**: When you run a project, `_mcp_screenshot.lua` is created and injected into `main.lua`
2. **Control file signaling**: The MCP server writes to a control file to start/stop recording
3. **Periodic capture**: Screenshots are captured every 1 second while recording is active
4. **JPEG compression**: Images are saved as JPEG at content resolution for smaller file sizes

### Screenshot Location

Screenshots are saved to: `/tmp/solar2d_screenshots_<project-name>/`

The directory is cleared when the simulator starts, but screenshots persist across recording sessions within the same run.

### Recording Workflow

```
User: Start recording screenshots for 30 seconds
Assistant: [calls start_screenshot_recording with duration=30]

User: Show me what the game looks like now
Assistant: [calls get_simulator_screenshot with which="latest"]
         [displays the screenshot for visual analysis]

User: Stop recording early
Assistant: [calls stop_screenshot_recording]
```

### Extending Recordings

You can call `start_screenshot_recording` while already recording to extend the duration. Screenshots continue from where they left off (not reset).

## Usage Examples

**Running a project and viewing logs:**
```
User: Run my Solar2D project and show me the logs
Assistant: [runs project] [waits a moment] [reads logs and shows output]
```

**Reading logs from manually-launched Solar2D:**
```
User: I'm running my game in the IDE, can you check the logs?
Assistant: [reads logs from /tmp/corona_log_my-game.txt] [shows recent output]
```

**Debugging with real-time logs:**
```
User: I'm seeing an error in my game, can you check the logs?
Assistant: [reads logs] I see the error at line X: [explains the issue]
```

**Capturing and analyzing screenshots:**
```
User: Run my game and show me what's on screen
Assistant: [runs project] [starts recording] [waits] [gets latest screenshot]
         I can see your game is showing the title screen with...
```

**Watching gameplay:**
```
User: Record 30 seconds of my game while I play
Assistant: [starts 30 second recording]
         Recording started! Play your game and I'll capture screenshots.

User: Ok I'm done, show me what you captured
Assistant: [lists screenshots] I captured 28 screenshots. Let me show you a few...
         [gets specific screenshots for analysis]
```

## Resources

- [MCP Documentation](https://modelcontextprotocol.io/)
- [Solar2D Documentation](https://docs.coronalabs.com/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
