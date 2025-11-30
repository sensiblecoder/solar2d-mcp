# Solar2D MCP Server

A Model Context Protocol (MCP) server for working with Solar2D (Corona SDK) projects. This server allows Claude to understand and help with Solar2D project development.

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

## Features

### Current

- `run_solar2d_project` tool - Run a Solar2D project in the simulator
  - Accepts project directory or main.lua path
  - Optional debug and console flags
  - Launches simulator in background
  - Injects logger that captures all print() output
- `read_solar2d_logs` tool - Read console logs from running Solar2D Simulator
  - View all Lua print() statements from your game code
  - Configurable number of recent lines to display
  - Helps debug your Lua code in real-time
  - **Automatic setup**: Logger is auto-injected into main.lua on first run
  - Note: Only captures Lua print() output, not Solar2D system messages
- `list_running_projects` tool - List all tracked Solar2D Simulator instances
  - Shows PID, status, and log file location
  - Useful for managing multiple running projects
- `solar2d://info` resource - Server information

### Possible Plans

- Ability to "see" the simulator
  - Ability to "watch" a manual play-through
  - Ability to "find" things it can "see"
- Basic ability to click and swipe things it "sees"
  - More complex ability to "play", based on "watching"
- Built-in Skills
  - Conventions & Good Practices
  - Common Patterns / Templates

## Development

The server uses the Model Context Protocol (MCP) Python SDK to communicate with Claude.

### Project Structure

```
Solar2DMCP/
├── server.py          # Main MCP server implementation
├── pyproject.toml     # Project dependencies and metadata
└── README.md          # This file
```

## Testing

Once configured, you can test the server by asking Claude:

- "Run my Solar2D project at /path/to/my-game"
- "Launch the Solar2D simulator with debug enabled for my project"
- "Show me the logs from my running Solar2D project"
- "Read the last 100 lines of Solar2D logs"
- "List all running Solar2D projects"
- "Show me the solar2d://info resource"

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

## Usage Examples

**Running a project and viewing logs:**
```
User: Run my Solar2D project and show me the logs
Claude: [runs project] [waits a moment] [reads logs and shows output]
```

**Reading logs from manually-launched Solar2D:**
```
User: I'm running my game in the IDE, can you check the logs?
Claude: [reads logs from /tmp/corona_log_my-game.txt] [shows recent output]
```

**Debugging with real-time logs:**
```
User: I'm seeing an error in my game, can you check the logs?
Claude: [reads logs] I see the error at line X: [explains the issue]
```

## Resources

- [MCP Documentation](https://modelcontextprotocol.io/)
- [Solar2D Documentation](https://docs.coronalabs.com/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
