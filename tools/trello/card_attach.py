"""
Trello card attachment — attach a file or simulator screenshot to a card.
"""

import os

from mcp.types import Tool, TextContent

from tools.trello.client import trello_request, trello_upload

TOOL = Tool(
    name="attach_to_trello_card",
    description=(
        "Attach a file or Solar2D simulator screenshot to a Trello card. "
        "For screenshots, use the same references as get_simulator_screenshot: "
        "'latest', 'last', a number, or a direct file path."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "card_id": {
                "type": "string",
                "description": "The Trello card ID"
            },
            "file_path": {
                "type": "string",
                "description": "Direct path to a file to attach"
            },
            "media": {
                "type": "string",
                "description": "Screenshot reference: 'latest', 'last', a number, or a file path. Uses same conventions as get_simulator_screenshot."
            },
            "project_path": {
                "type": "string",
                "description": "Path to Solar2D project (needed if media is 'latest', 'last', or a number)"
            },
            "name": {
                "type": "string",
                "description": "Display name for the attachment (defaults to filename)"
            }
        },
        "required": ["card_id"]
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle attach_to_trello_card tool call."""
    try:
        import httpx
    except ImportError:
        return [TextContent(
            type="text",
            text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[trello]'"
        )]

    card_id = arguments.get("card_id")
    file_path = arguments.get("file_path")
    media = arguments.get("media")
    project_path = arguments.get("project_path")
    display_name = arguments.get("name")

    if not card_id:
        return [TextContent(type="text", text="Error: card_id is required.")]

    if not file_path and not media:
        return [TextContent(
            type="text",
            text="Error: Provide either file_path or media reference."
        )]

    # Resolve the file to attach
    resolved_path = None

    if file_path:
        if os.path.isfile(file_path):
            resolved_path = file_path
        else:
            return [TextContent(type="text", text=f"Error: File not found: {file_path}")]
    elif media:
        # Reuse the screenshot resolution logic from social/preview.py
        from tools.social.preview import _resolve_media_path
        resolved_path = _resolve_media_path(media, project_path)
        if not resolved_path:
            return [TextContent(
                type="text",
                text=f"Error: Could not resolve media '{media}'. "
                     f"Use 'latest', 'last', a number, or a direct file path. "
                     f"If using screenshot references, provide project_path."
            )]

    filename = display_name or os.path.basename(resolved_path)

    try:
        attachment = await trello_upload(
            f"/cards/{card_id}/attachments",
            resolved_path,
            filename,
        )
    except Exception as e:
        return [TextContent(type="text", text=f"Error uploading attachment: {e}")]

    return [TextContent(
        type="text",
        text=f"Attachment added to card {card_id}.\n"
             f"Name: {attachment.get('name', filename)}\n"
             f"URL: {attachment.get('url', 'N/A')}"
    )]
