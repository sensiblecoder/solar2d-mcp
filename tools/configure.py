"""
configure_solar2d tool - Configure the Solar2D simulator path.
"""

import os

from mcp.types import Tool, TextContent

import config


TOOL = Tool(
    name="configure_solar2d",
    description="Configure or verify the Solar2D simulator path. Use this to set up the simulator location or change it later.",
    inputSchema={
        "type": "object",
        "properties": {
            "simulator_path": {
                "type": "string",
                "description": "Path to the Solar2D/Corona Simulator executable. If not provided, will auto-detect and show options."
            },
            "confirm": {
                "type": "boolean",
                "description": "Set to true to confirm and save the auto-detected path.",
                "default": False
            }
        },
        "required": []
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle configure_solar2d tool call."""
    simulator_path = arguments.get("simulator_path")
    confirm = arguments.get("confirm", False)

    # If user provided a specific path, validate and save it
    if simulator_path:
        if os.path.exists(simulator_path):
            config.set_simulator_path(simulator_path)
            return [TextContent(
                type="text",
                text=f"✓ Solar2D simulator configured successfully!\n\nPath: {simulator_path}\n\nThis setting has been saved and will be remembered for future sessions."
            )]
        else:
            return [TextContent(
                type="text",
                text=f"✗ Error: Path does not exist: {simulator_path}\n\nPlease provide a valid path to the Solar2D/Corona Simulator executable."
            )]

    # Auto-detect and show options
    current_path, detected_paths, needs_confirmation = config.get_simulator_or_detect()

    # If confirm=True and we have a path, save it
    if confirm and current_path:
        config.set_simulator_path(current_path)
        return [TextContent(
            type="text",
            text=f"✓ Solar2D simulator confirmed and saved!\n\nPath: {current_path}\n\nThis setting has been saved and will be remembered for future sessions."
        )]

    # Build response showing current state and options
    lines = []

    if config.is_configured():
        lines.append(f"Current configuration: {config.get_simulator_path()}")
        lines.append("")

    if detected_paths:
        lines.append("Detected Solar2D simulators:")
        for i, path in enumerate(detected_paths, 1):
            marker = " (recommended)" if path == detected_paths[-1] else ""
            lines.append(f"  {i}. {path}{marker}")
        lines.append("")

        if needs_confirmation:
            lines.append("To use the recommended path, call this tool with confirm=true")
            lines.append("Or provide a specific path with simulator_path=\"/path/to/simulator\"")
    else:
        lines.append("No Solar2D simulators detected in common locations.")
        lines.append("")
        lines.append("Please provide the path manually:")
        lines.append("  configure_solar2d(simulator_path=\"/path/to/Corona Simulator.app/Contents/MacOS/Corona Simulator\")")
        lines.append("")
        lines.append("Common locations:")
        lines.append("  - /Applications/Corona-XXXX/Corona Simulator.app/Contents/MacOS/Corona Simulator")
        lines.append("  - /Applications/Solar2D-XXXX/Solar2D Simulator.app/Contents/MacOS/Solar2D Simulator")

    return [TextContent(type="text", text="\n".join(lines))]
