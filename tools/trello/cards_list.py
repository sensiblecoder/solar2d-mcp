"""
Trello card listing — list cards by lane with optional label filtering and priority sorting.
"""

from datetime import datetime, timezone

from mcp.types import Tool, TextContent

from tools.trello.client import (
    get_board_id, get_lane_map, get_label_map, resolve_lane_id,
    trello_request, LANE_NAMES,
)

# Cards in in_progress or blocked lanes for longer than this get flagged
STALE_HOURS = 24

TOOL = Tool(
    name="list_trello_cards",
    description=(
        "List cards on the configured Trello board, optionally filtered by lane and/or label. "
        "Cards with the 'priority' label are sorted first. "
        "Lanes: ideas, planning, blocked_plan, backlog, in_progress, blocked_work, done."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "lane": {
                "type": "string",
                "description": "Filter to a specific lane (e.g. 'backlog', 'in_progress'). If omitted, shows all lanes."
            },
            "label": {
                "type": "string",
                "description": "Filter to cards with this label (e.g. 'bug', 'priority')."
            }
        },
        "required": []
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle list_trello_cards tool call."""
    try:
        import httpx
    except ImportError:
        return [TextContent(
            type="text",
            text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[trello]'"
        )]

    board_id = get_board_id()
    if not board_id:
        return [TextContent(
            type="text",
            text="Error: No board selected. Use configure_trello first."
        )]

    lane_map = get_lane_map()
    if not lane_map:
        return [TextContent(
            type="text",
            text="Error: No lane mapping. Run setup_trello_board first."
        )]

    lane_filter = arguments.get("lane")
    label_filter = arguments.get("label")

    # Validate lane filter
    if lane_filter and lane_filter not in LANE_NAMES:
        return [TextContent(
            type="text",
            text=f"Error: Unknown lane '{lane_filter}'. Valid: {', '.join(LANE_NAMES.keys())}"
        )]

    # Determine which list IDs to fetch
    if lane_filter:
        list_id = resolve_lane_id(lane_filter)
        if not list_id:
            return [TextContent(
                type="text",
                text=f"Error: Lane '{lane_filter}' not mapped. Run setup_trello_board."
            )]
        target_lists = {lane_filter: list_id}
    else:
        target_lists = lane_map

    # Resolve label filter to ID
    label_map = get_label_map()
    filter_label_id = None
    if label_filter:
        filter_label_id = label_map.get(label_filter)
        if not filter_label_id:
            return [TextContent(
                type="text",
                text=f"Error: Unknown label '{label_filter}'. Valid: {', '.join(label_map.keys())}"
            )]

    # Build reverse map: list_id -> role name
    id_to_role = {v: k for k, v in lane_map.items()}

    # Fetch cards for each list
    priority_label_id = label_map.get("priority")
    all_sections = []

    stale_lanes = {"in_progress", "blocked_plan", "blocked_work"}
    stale_warnings = []
    now = datetime.now(timezone.utc)

    for role, list_id in target_lists.items():
        try:
            cards = await trello_request(
                "GET", f"/lists/{list_id}/cards",
                params={"fields": "name,idLabels,due,shortUrl,pos,dateLastActivity", "members": "false"}
            )
        except Exception as e:
            all_sections.append(f"## {LANE_NAMES.get(role, role)}\n  Error: {e}")
            continue

        # Filter by label if requested
        if filter_label_id:
            cards = [c for c in cards if filter_label_id in c.get("idLabels", [])]

        if not cards:
            continue

        # Sort: priority cards first, then by position
        def sort_key(card):
            has_priority = priority_label_id in card.get("idLabels", []) if priority_label_id else False
            return (0 if has_priority else 1, card.get("pos", 0))

        cards.sort(key=sort_key)

        # Format
        section_lines = [f"## {LANE_NAMES.get(role, role)} ({len(cards)} cards)"]
        for card in cards:
            label_names = _resolve_label_names(card.get("idLabels", []), label_map)
            labels_str = f" [{', '.join(label_names)}]" if label_names else ""
            due_str = f" (due: {card['due'][:10]})" if card.get("due") else ""

            # Check for stale cards
            stale_str = ""
            if role in stale_lanes and card.get("dateLastActivity"):
                try:
                    last_activity = datetime.fromisoformat(card["dateLastActivity"].replace("Z", "+00:00"))
                    hours_idle = (now - last_activity).total_seconds() / 3600
                    if hours_idle >= STALE_HOURS:
                        days_idle = int(hours_idle // 24)
                        stale_str = f" *** STALE ({days_idle}d idle) ***"
                        stale_warnings.append((card["name"], card["id"], role, days_idle))
                except (ValueError, TypeError):
                    pass

            section_lines.append(f"  - {card['name']}{labels_str}{due_str}{stale_str}")
            section_lines.append(f"    ID: {card['id']}")

        all_sections.append("\n".join(section_lines))

    if not all_sections:
        filters = []
        if lane_filter:
            filters.append(f"lane={lane_filter}")
        if label_filter:
            filters.append(f"label={label_filter}")
        filter_desc = f" (filters: {', '.join(filters)})" if filters else ""
        return [TextContent(type="text", text=f"No cards found{filter_desc}.")]

    result = "\n\n".join(all_sections)

    # Append stale card warnings
    if stale_warnings:
        warning_lines = [
            "",
            "---",
            "ACTION REQUIRED — Stale cards detected:",
        ]
        for name, cid, role, days in stale_warnings:
            if role == "in_progress":
                warning_lines.append(
                    f"  - \"{name}\" ({cid}) has been In Progress for {days}d. "
                    f"Move to 'done' or 'blocked_work' (with blocked_reason)."
                )
            else:
                warning_lines.append(
                    f"  - \"{name}\" ({cid}) has been in {LANE_NAMES[role]} for {days}d. "
                    f"Needs user attention."
                )
        result += "\n".join(warning_lines)

    return [TextContent(type="text", text=result)]


def _resolve_label_names(label_ids: list[str], label_map: dict) -> list[str]:
    """Resolve Trello label IDs back to names."""
    id_to_name = {v: k for k, v in label_map.items()}
    return [id_to_name[lid] for lid in label_ids if lid in id_to_name]
