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
- Project analysis
- Code context extraction
- Build configuration help
- API reference

Status: Hello World Implementation
"""
