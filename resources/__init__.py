"""
Solar2D MCP Resources - Resource definitions and reader.
"""

from mcp.types import Resource

from resources import info


# Collect all resources
RESOURCES: list[Resource] = [
    info.RESOURCE,
]

# Map resource URIs to readers
_READERS = {
    "solar2d://info": info.read,
}


def read_resource(uri: str) -> str:
    """Read a resource by URI."""
    reader = _READERS.get(uri)
    if reader is None:
        raise ValueError(f"Unknown resource: {uri}")
    return reader()
