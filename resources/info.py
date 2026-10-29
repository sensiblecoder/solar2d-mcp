"""
solar2d://info resource - Server information.
"""

from mcp.types import Resource

RESOURCE = Resource(
    uri="solar2d://info",
    name="Solar2D Server Info",
    mimeType="text/plain",
    description="Information about this Solar2D MCP server"
)


def read() -> str:
    """Read the info resource."""
    return """Solar2D MCP Server v0.1.0

This is a Model Context Protocol server for working with Solar2D (Corona SDK) projects.

Capabilities:
- Launch projects in the Solar2D Simulator and read Lua print() logs
- Capture screenshots / recordings and encode them to MP4
- Simulate taps and drags, and locate touchable objects
- Read structured game state and run test scenarios
- Run SolarScope tests and read their results
- Experimental: Trello board and social media integrations
"""
