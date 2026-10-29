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

   Optional extras for the experimental integrations:
   ```bash
   pip install -e ".[trello,social]"
   ```

   `encode_recording_video` also needs [ffmpeg](https://ffmpeg.org/) on the host (`brew install ffmpeg`).

   The SolarScope test tools need the [SolarScope](https://github.com/sensiblecoder/solar-scope)
   runtime added to your game (see [SolarScope Tests](#solarscope-tests)).

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
  - Captures at 10 fps (100ms interval)
  - Default recording duration: 60 seconds (max: 300 seconds / 5 minutes)
  - The 300s ceiling is enforced in the Lua capture loop too, so a recording
    stops on its own even if `stop_screenshot_recording` is never called
  - Can extend recording while already capturing
- `stop_screenshot_recording` - Stop screenshot recording early
- `get_simulator_screenshot` - Get screenshot(s) for visual analysis
  - `which="latest"` - Capture fresh screenshot now (default)
  - `which="last"` - Get most recent from recording session
  - `which="all"` - List all recorded screenshots
  - `which="5"` - Get specific recorded screenshot by number
- `list_screenshots` - List all available screenshots with file sizes
- `encode_recording_video` - Stitch a recording session's frames into an MP4
  - Optional `fps`, `width`, `start_frame`/`end_frame`, and `filename`
  - Written to a `video/` subfolder of the screenshot directory
  - MP4 plays inline in the Claude app (a GIF does not) and is smaller
  - Requires ffmpeg
- `simulate_tap` - Tap/click on the simulator screen
  - Uses percentage-based bounding box (left, right, top, bottom)
  - Taps the center of the specified area
  - Example: button at 30-50% horizontal, 60-70% vertical
- `simulate_drag` - Drag/swipe between two points on the simulator screen
  - Percentage-based start and end bounding boxes
  - Configurable drag duration
  - Useful for swipes, card plays, and sliders
- `find_object` - Locate touchable display objects on screen
  - Reports positions so taps/drags can be targeted precisely
- `get_display_info` - Get display coordinate system info

#### Game State & Scenarios

- `get_game_state` - Get structured game state as JSON
  - Returns current scene, combat state, player stats, and UI state
  - Much faster and more reliable than parsing screenshots
- `run_scenario` - Configure and launch a test scenario without restarting
  - Load a saved scenario from `scenarios/` or pass settings inline
  - Optionally seed `math.random` for deterministic replay
  - Supports scripted scenarios with a `steps` array that runs a
    pass/fail test (actions: `wait_for`, `verify`, `wait`, `tap`, `drag`,
    `play_card`, `tap_stat`, `tap_choice`)
- `list_scenarios` - List saved scenario files from the project's `scenarios/` folder

#### SolarScope Tests

Drive [SolarScope](https://github.com/sensiblecoder/solar-scope), an in-game
test framework for Solar2D ("Playwright for Solar2D"). Tests are plain Lua that
run inside the simulator. They drive the real UI through hit-tested input and
assert on structured game state.

> **Optional dependency.** SolarScope is only needed for the three tools below.
> The rest of the server works without it. These tools don't install SolarScope.
> They write a command to `<project>/.solar_scope/command.json` and read the
> result the framework writes to the simulator sandbox, so the game must already
> include the SolarScope runtime. To add it, copy `solar_scope.lua` and the
> `solar_scope/` folder from the SolarScope repo into your project. See its
> [README](https://github.com/sensiblecoder/solar-scope#readme) for details.
>
> Results are read from `~/Library/Application Support/Corona Simulator/<project>-*/Documents/solar_scope/`,
> so these tools currently work on macOS only.

- `run_solar_scope_test` - Launch the project running a specific test module
  (e.g. `tests.regression.match_clears`) without editing the game's config
  - Replaces any running instance
  - Returns a command sequence number for `get_solar_scope_result`
- `rerun_solar_scope_test` - Hot-reload a test into an already-running simulator
  - Much faster than relaunching when iterating on a test
- `get_solar_scope_result` - Read the structured result of the latest run
  (status, message, errors, artifacts, probe report)
  - Pass `wait_seq` to poll until that run's result appears (`timeout_ms`, default 8000)

### Resources

- `solar2d://info` - Server information

### Experimental / WIP

These integrations are in progress and their tool surface may change:

- **Trello** - Manage a project board from the assistant:
  `configure_trello`, `setup_trello_board`, `create_trello_card`,
  `list_trello_cards`, `get_trello_card`, `update_trello_card`,
  `comment_trello_card`, `attach_to_trello_card`
- **Social media** - Draft and publish posts:
  `configure_social_media`, `preview_social_post`, `publish_social_post`

### Possible Plans

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
│   ├── screenshot.py  # Screenshot recording + MP4 encode tools
│   ├── touch.py       # Touch/drag simulation tools
│   ├── state.py       # Game state & test scenario tools
│   ├── solar_scope.py # SolarScope test-runner tools
│   ├── social/        # Social media tools (experimental)
│   └── trello/        # Trello board tools (experimental)
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
- "Record 20 seconds of gameplay and give me an MP4"
- "Run the SolarScope test tests.regression.match_clears and report the result"

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

- Log file location: `<tempdir>/corona_log_<project-name>.txt`, where `<tempdir>` is Python's `tempfile.gettempdir()` (`$TMPDIR`, usually under `/var/folders/...` on macOS)
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
3. **Periodic capture**: Screenshots are captured every 100ms (10 fps) while recording is active
4. **JPEG compression**: Images are saved as JPEG at content resolution for smaller file sizes

### Screenshot Location

Screenshots are saved to: `<tempdir>/solar2d_screenshots_<project-name>/` (same temp directory as the log file)

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

## Touch Interaction

The MCP server can simulate taps on the running simulator, allowing the AI to interact with your game!

### How It Works

1. **Auto-injected module**: `_mcp_touch.lua` is created and injected into `main.lua`
2. **Hit testing**: The module finds touchable objects at the tap location
3. **Event dispatch**: Synthetic touch events are sent to the target object

### Percentage-Based Coordinates

Taps use a bounding box with percentage coordinates (0-100):
- `left`, `right`: Horizontal bounds (0=left edge, 100=right edge)
- `top`, `bottom`: Vertical bounds (0=top edge, 100=bottom edge)

The tool taps the **center** of the bounding box. This makes it easy for the AI to estimate positions visually from screenshots.

### Example Workflow

```
User: Click on the play button
Assistant: [calls get_simulator_screenshot to see current state]
         I can see a play button in the center of the screen.
         [calls simulate_tap with left=40, right=60, top=45, bottom=55]
         Tapped the play button!

User: Click on any popup buttons you see
Assistant: [calls get_simulator_screenshot]
         I see a "Continue" button at the bottom of the screen.
         [calls simulate_tap with left=30, right=70, top=80, bottom=90]
         Tapped the Continue button.
```

## Resources

- [MCP Documentation](https://modelcontextprotocol.io/)
- [Solar2D Documentation](https://docs.coronalabs.com/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [SolarScope](https://github.com/sensiblecoder/solar-scope) - In-game Lua test framework driven by the SolarScope tools

## License

[MIT](LICENSE) © 2025-2026 Under Byte Studios, LLC
