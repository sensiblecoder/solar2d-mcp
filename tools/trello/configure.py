"""
Trello configuration — save API key, token, and select board.
"""

from mcp.types import Tool, TextContent

from tools.trello.client import (
    get_trello_config, save_trello_config, get_auth_params, API_BASE,
)

TOOL = Tool(
    name="configure_trello",
    description="Configure Trello integration. Save your API key and token, then select a board. Get your API key from https://trello.com/power-ups/admin and generate a token from the key page.",
    inputSchema={
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "description": "Your Trello API key from https://trello.com/power-ups/admin"
            },
            "api_token": {
                "type": "string",
                "description": "Your Trello API token (generate from key page)"
            },
            "board_id": {
                "type": "string",
                "description": "Trello board ID to use. If omitted, lists your boards so you can pick one."
            }
        },
        "required": []
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle configure_trello tool call."""
    api_key = arguments.get("api_key")
    api_token = arguments.get("api_token")
    board_id = arguments.get("board_id")

    tc = get_trello_config()

    # Save credentials if provided
    if api_key:
        tc["api_key"] = api_key
    if api_token:
        tc["api_token"] = api_token

    if api_key or api_token:
        save_trello_config(tc)

    # If no credentials at all, show status
    if not tc.get("api_key") or not tc.get("api_token"):
        return [TextContent(
            type="text",
            text="Trello not configured.\n\n"
                 "1. Get your API key from https://trello.com/power-ups/admin\n"
                 "2. Generate a token from the key page\n"
                 "3. Call configure_trello with api_key and api_token"
        )]

    # Import httpx for API calls
    try:
        import httpx
    except ImportError:
        return [TextContent(
            type="text",
            text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[trello]'"
        )]

    # If board_id provided, save it and confirm
    if board_id:
        try:
            board = await _fetch_board(board_id)
        except Exception as e:
            return [TextContent(type="text", text=f"Error fetching board: {e}")]

        tc["board_id"] = board_id
        save_trello_config(tc)
        return [TextContent(
            type="text",
            text=f"Board selected: {board['name']} ({board_id})\n\n"
                 f"Next step: run setup_trello_board to create/map workflow lanes and labels."
        )]

    # Verify credentials by fetching boards
    try:
        boards = await _fetch_boards()
    except httpx.HTTPStatusError as e:
        return [TextContent(
            type="text",
            text=f"Error: Trello API returned {e.response.status_code}. Check your API key and token."
        )]
    except httpx.RequestError as e:
        return [TextContent(type="text", text=f"Error connecting to Trello: {e}")]

    if not boards:
        return [TextContent(
            type="text",
            text="Credentials saved but no boards found. Create a board on Trello first."
        )]

    # Show boards for selection
    masked_key = tc["api_key"][:8] + "..."
    lines = [
        f"Trello API key saved: {masked_key}",
        f"Token saved.",
        "",
        "Your boards:",
    ]
    for b in boards:
        current = " (selected)" if b["id"] == tc.get("board_id") else ""
        lines.append(f"  - {b['name']}: {b['id']}{current}")

    lines.append("")
    lines.append("Call configure_trello with board_id to select a board.")

    return [TextContent(type="text", text="\n".join(lines))]


async def _fetch_boards() -> list[dict]:
    """Fetch user's boards from Trello."""
    from tools.trello.client import trello_request
    return await trello_request("GET", "/members/me/boards", params={"fields": "name,id,url"})


async def _fetch_board(board_id: str) -> dict:
    """Fetch a single board by ID."""
    from tools.trello.client import trello_request
    return await trello_request("GET", f"/boards/{board_id}", params={"fields": "name,id,url"})
