"""
Trello card comment — add a comment to a card.
"""

from mcp.types import Tool, TextContent

from tools.trello.client import trello_request

TOOL = Tool(
    name="comment_trello_card",
    description="Add a comment to a Trello card. Useful for logging progress, results, or notes.",
    inputSchema={
        "type": "object",
        "properties": {
            "card_id": {
                "type": "string",
                "description": "The Trello card ID"
            },
            "text": {
                "type": "string",
                "description": "Comment text (Markdown supported)"
            }
        },
        "required": ["card_id", "text"]
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle comment_trello_card tool call."""
    try:
        import httpx
    except ImportError:
        return [TextContent(
            type="text",
            text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[trello]'"
        )]

    card_id = arguments.get("card_id")
    text = arguments.get("text")

    if not card_id:
        return [TextContent(type="text", text="Error: card_id is required.")]
    if not text:
        return [TextContent(type="text", text="Error: text is required.")]

    try:
        comment = await trello_request(
            "POST", f"/cards/{card_id}/actions/comments",
            params={"text": text}
        )
    except Exception as e:
        return [TextContent(type="text", text=f"Error adding comment: {e}")]

    return [TextContent(
        type="text",
        text=f"Comment added to card {card_id}.\n\n"
             f"Preview: {text[:100]}{'...' if len(text) > 100 else ''}"
    )]
