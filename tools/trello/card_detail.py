"""
Trello card detail — full card info including description, checklist, comments, attachments.
"""

from mcp.types import Tool, TextContent

from tools.trello.client import get_label_map, resolve_lane_role, trello_request, LANE_NAMES

TOOL = Tool(
    name="get_trello_card",
    description=(
        "Get full details of a Trello card: name, description, checklist items, "
        "comments, attachments, labels, due date, and lane.\n\n"
        "IMPORTANT — COMMENT WORKFLOW:\n"
        "Always read the comments carefully. The most recent comment is shown first "
        "and may be a call-to-action (CTA) from the user.\n\n"
        "When the latest comment is a CTA (question, request, feedback):\n"
        "  1. DO NOT start implementing or writing code\n"
        "  2. Respond to the CTA by adding a comment with your analysis/plan/answer\n"
        "  3. Move the card to blocked_plan — it needs user review before proceeding\n"
        "  4. Only move to backlog/in_progress AFTER the user unblocks it\n\n"
        "The card's lane must always reflect its true status. If you need user input, "
        "the card belongs in blocked_plan, not planning."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "card_id": {
                "type": "string",
                "description": "The Trello card ID"
            }
        },
        "required": ["card_id"]
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle get_trello_card tool call."""
    try:
        import httpx
    except ImportError:
        return [TextContent(
            type="text",
            text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[trello]'"
        )]

    card_id = arguments.get("card_id")
    if not card_id:
        return [TextContent(type="text", text="Error: card_id is required.")]

    try:
        card = await trello_request(
            "GET", f"/cards/{card_id}",
            params={
                "fields": "name,desc,idList,idLabels,due,shortUrl,dateLastActivity",
                "checklists": "all",
                "checkItemStates": "true",
                "attachments": "true",
                "attachment_fields": "name,url,date",
            }
        )
    except Exception as e:
        return [TextContent(type="text", text=f"Error fetching card: {e}")]

    # Fetch comments (actions of type commentCard)
    try:
        actions = await trello_request(
            "GET", f"/cards/{card_id}/actions",
            params={"filter": "commentCard", "fields": "data,date,memberCreator"}
        )
    except Exception:
        actions = []

    # Build output
    label_map = get_label_map()
    id_to_name = {v: k for k, v in label_map.items()}

    lane_role = resolve_lane_role(card.get("idList", ""))
    lane_display = LANE_NAMES.get(lane_role, "Unknown") if lane_role else "Unknown"

    lines = [f"# {card.get('name', 'Untitled')}"]
    lines.append(f"ID: {card_id}")
    lines.append(f"Lane: {lane_display} ({lane_role or '?'})")
    lines.append(f"URL: {card.get('shortUrl', 'N/A')}")

    if card.get("due"):
        lines.append(f"Due: {card['due'][:10]}")

    label_names = [id_to_name.get(lid, lid) for lid in card.get("idLabels", [])]
    if label_names:
        lines.append(f"Labels: {', '.join(label_names)}")

    lines.append(f"Last activity: {card.get('dateLastActivity', 'N/A')}")

    # Description
    desc = card.get("desc", "").strip()
    if desc:
        lines.append("")
        lines.append("## Description")
        lines.append(desc)

    # Checklists
    checklists = card.get("checklists", [])
    if checklists:
        lines.append("")
        lines.append("## Checklists")
        for cl in checklists:
            lines.append(f"\n### {cl.get('name', 'Checklist')}")
            for item in cl.get("checkItems", []):
                state = "x" if item.get("state") == "complete" else " "
                lines.append(f"  [{state}] {item.get('name', '')}")

    # Attachments
    attachments = card.get("attachments", [])
    if attachments:
        lines.append("")
        lines.append("## Attachments")
        for att in attachments:
            lines.append(f"  - {att.get('name', 'file')}: {att.get('url', 'N/A')}")

    # Comments — most recent first (Trello API returns newest first)
    if actions:
        lines.append("")
        lines.append("## Comments")
        for idx, action in enumerate(actions):
            data = action.get("data", {})
            text = data.get("text", "")
            date = action.get("date", "")[:10]
            author = action.get("memberCreator", {}).get("fullName", "Unknown")
            if idx == 0:
                lines.append("")
                lines.append(">>> LATEST COMMENT (may be a call-to-action) <<<")
                lines.append(f"**{author}** ({date}):")
                lines.append(text)
                lines.append(">>> END LATEST COMMENT <<<")
            else:
                lines.append(f"\n**{author}** ({date}):")
                lines.append(text)

    return [TextContent(type="text", text="\n".join(lines))]
