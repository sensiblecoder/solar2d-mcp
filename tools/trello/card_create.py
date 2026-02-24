"""
Trello card creation — create a card with lane, labels, description, and checklist.
"""

from mcp.types import Tool, TextContent

from tools.trello.client import (
    resolve_lane_id, resolve_label_ids, trello_request, LANE_NAMES,
)

TOOL = Tool(
    name="create_trello_card",
    description=(
        "Create a new Trello card in a specified lane with optional labels, description, "
        "due date, and checklist items.\n\n"
        "Lanes: ideas, planning, blocked_plan, backlog, in_progress, blocked_work, done\n"
        "Labels: bug, priority, ai-created, needs-screenshot, shareable"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Card title"
            },
            "lane": {
                "type": "string",
                "description": "Lane to place the card in (e.g. 'backlog', 'planning')"
            },
            "description": {
                "type": "string",
                "description": "Card description (Markdown supported)"
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Labels to apply (e.g. ['bug', 'priority'])"
            },
            "due": {
                "type": "string",
                "description": "Due date in ISO 8601 format (e.g. '2025-03-01')"
            },
            "checklist": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Checklist items to add to the card"
            }
        },
        "required": ["name", "lane"]
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle create_trello_card tool call."""
    try:
        import httpx
    except ImportError:
        return [TextContent(
            type="text",
            text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[trello]'"
        )]

    name = arguments.get("name")
    lane = arguments.get("lane")
    description = arguments.get("description", "")
    labels = arguments.get("labels", [])
    due = arguments.get("due")
    checklist_items = arguments.get("checklist", [])

    if not name:
        return [TextContent(type="text", text="Error: name is required.")]
    if not lane:
        return [TextContent(type="text", text="Error: lane is required.")]

    # Resolve lane to list ID
    list_id = resolve_lane_id(lane)
    if not list_id:
        if lane not in LANE_NAMES:
            return [TextContent(
                type="text",
                text=f"Error: Unknown lane '{lane}'. Valid: {', '.join(LANE_NAMES.keys())}"
            )]
        return [TextContent(
            type="text",
            text=f"Error: Lane '{lane}' not mapped. Run setup_trello_board first."
        )]

    # Resolve labels to IDs
    label_ids = resolve_label_ids(labels)

    # Create the card
    create_params = {
        "name": name,
        "idList": list_id,
        "desc": description,
        "pos": "bottom",
    }
    if label_ids:
        create_params["idLabels"] = ",".join(label_ids)
    if due:
        create_params["due"] = due

    try:
        card = await trello_request("POST", "/cards", params=create_params)
    except Exception as e:
        return [TextContent(type="text", text=f"Error creating card: {e}")]

    card_id = card["id"]

    # Add checklist if items provided
    if checklist_items:
        try:
            checklist = await trello_request(
                "POST", f"/cards/{card_id}/checklists",
                params={"name": "Tasks"}
            )
            cl_id = checklist["id"]
            for item in checklist_items:
                await trello_request(
                    "POST", f"/checklists/{cl_id}/checkItems",
                    params={"name": item}
                )
        except Exception as e:
            # Card created but checklist failed - report partial success
            return [TextContent(
                type="text",
                text=f"Card created but checklist failed: {e}\n\n"
                     f"Card: {card.get('name')}\n"
                     f"ID: {card_id}\n"
                     f"URL: {card.get('shortUrl', 'N/A')}"
            )]

    # Success
    lines = [
        f"Card created: {card.get('name')}",
        f"ID: {card_id}",
        f"Lane: {lane} ({LANE_NAMES.get(lane, lane)})",
        f"URL: {card.get('shortUrl', 'N/A')}",
    ]
    if labels:
        lines.append(f"Labels: {', '.join(labels)}")
    if due:
        lines.append(f"Due: {due}")
    if checklist_items:
        lines.append(f"Checklist: {len(checklist_items)} items")

    return [TextContent(type="text", text="\n".join(lines))]
