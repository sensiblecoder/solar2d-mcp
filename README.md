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

   Video recording (macOS) needs the Xcode command line tools (`swiftc` builds the recorder on first use),
   [ffmpeg](https://ffmpeg.org/) for exports (`brew install ffmpeg`), and Screen Recording permission for
   the terminal/app that launches the MCP server (System Settings > Privacy & Security > Screen & System
   Audio Recording).

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
- `get_simulator_screenshot` - Get a still for visual analysis
  - Default: capture the live simulator now
  - `video_time` - pull a full-resolution still out of a video recording instead
    (`recording` picks one, default the newest; `save_to` writes the full-res PNG)
- `start_video_recording` - Record the simulator window as video (see [Recording Video](#recording-video))
  - Native Retina resolution, 60fps, the simulator's own audio, title bar cropped off
  - `duration` (default 60s, max 600s), `name`, `fps`, `codec` (`hevc` / `prores`), `audio`, `crop`
- `stop_video_recording` - Stop it, wait for the file, report frames and delivered fps
- `export_video` - Cut a recording for delivery: presets `x` (1920x1080 60fps), `youtube`
  (2560x1440 60fps), `vertical` (1080x1920, aim with `focus_x`), `preview` (960px 30fps),
  `master` (ProRes 422 HQ); trim with `start`/`end`
- `list_video_recordings` - Recordings and exports with duration, size and resolution
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
- **AI art (OpenAI image models)** - Generate sprites, backgrounds, icons and UI art
  (`pip install -e ".[art]"`):
  - `configure_art_generation` - Save an OpenAI API key, check it, and list the image models
    it can use. The key goes in `~/.config/solar2d-mcp/config.json` (owner-only permissions),
    never the project; `OPENAI_API_KEY` in the server's environment works too. Optional
    `organization_id` / `project_id` send requests under a specific org or project.
  - `generate_art` - Prompt to image. `size`, `quality` (`low` for drafts), `background:
    transparent` for sprites, `n` variations, `model` (default `gpt-image-2`; `gpt-image-1.5` for transparent backgrounds, which `gpt-image-2` rejects).
  - `edit_art` - Rework existing images or draw new art that matches them: pass reference
    images (sprites, a simulator screenshot) and optionally a `mask` to redraw one region.
  - Files are saved full-size to `save_to` (e.g. `<project>/images/hero.png`) or
    `~/Pictures/solar2d-mcp/<project>/art/`; the tool returns a downscaled preview.

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
│   ├── screenshot.py  # get_simulator_screenshot (live or from a recording)
│   ├── video.py       # 60fps window recording + export presets
│   ├── touch.py       # Touch/drag simulation tools
│   ├── state.py       # Game state & test scenario tools
│   ├── solar_scope.py # SolarScope test-runner tools
│   ├── art/           # OpenAI image generation tools (experimental)
│   ├── social/        # Social media tools (experimental)
│   └── trello/        # Trello board tools (experimental)
├── capture/
│   └── simcap.swift   # ScreenCaptureKit window recorder (built to capture/.build/)
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
- "Record 20 seconds of gameplay and export it for X"
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

`get_simulator_screenshot` writes `"now"` to a control file; the auto-injected
`_mcp_screenshot.lua` saves one JPEG at content resolution to
`<tempdir>/solar2d_screenshots_<project-name>/screenshot_latest.jpg` and the tool
returns it. Nothing in the game runs per frame for it.

## Recording Video

Video is recorded outside the game, from the simulator's window, by `capture/simcap`
(ScreenCaptureKit; compiled from `capture/simcap.swift` the first time it is needed).
The game does no work for it, so a recording runs at the simulator's own frame rate
(60fps) instead of the stuttering 10fps a `display.save` loop could manage.

- **Picture:** the simulator window at native Retina pixels (a 1728x972pt window is
  3456x1944), cropped to the game's content aspect so the title bar is gone. The aspect
  comes from the display info the touch module writes; `crop: false` keeps the whole window.
  The window can sit behind other windows, but not be minimized.
- **Sound:** the simulator's own audio only, not the rest of the machine.
- **Frames:** ScreenCaptureKit only sends a frame when the window changed, so a still
  screen lowers the delivered count. Exports are constant frame rate.
- **Masters** are kept in `~/Movies/solar2d-mcp/<project>/<name>.mov` (HEVC ~60Mbps, or
  ProRes 422 HQ with `codec: prores`); exports go to its `exports/` folder.
- **Control:** the recorder runs detached and stops on `stop_video_recording`, after
  `duration`, or on SIGINT. Its state lives in `<tempdir>/solar2d_video_<project>.json`,
  so any MCP server process can stop a recording another one started.
- **Markers:** `simulate_tap` / `find_object` draw indicators into the game frame. Drive
  takes meant for posting with a SolarScope harness instead.

```
User: Record the boss intro and give me something for X
Assistant: [start_video_recording name="boss-intro" duration=40]
           [run_solar_scope_test test="tests.regression.boss_intro"]
           [stop_video_recording]
           [export_video preset="x" start=2 end=32]
```

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
