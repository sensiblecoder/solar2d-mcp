"""
Trello board setup — create/map workflow lanes and labels.
"""

from mcp.types import Tool, TextContent

from tools.trello.client import (
    get_trello_config, save_trello_config, get_board_id,
    trello_request, LANE_NAMES, LABEL_DEFS,
)

TOOL = Tool(
    name="setup_trello_board",
    description=(
        "Create or map workflow lanes and labels on the configured Trello board. "
        "Scans existing lists and labels, matches by exact name (case-insensitive), "
        "and creates anything missing.\n\n"
        "Expected lanes: Ideas, Planning, Blocked:Plan, Backlog, In Progress, Blocked:Work, Done\n"
        "Expected labels: bug (red), priority (yellow), ai-created (purple), "
        "needs-screenshot (orange), shareable (pink)\n\n"
        "Use mode='map' to manually assign existing lists to roles instead of auto-matching."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": "'auto' (default) to match by name and create missing, or 'map' to manually assign lists to roles.",
                "default": "auto"
            },
            "lane_assignments": {
                "type": "object",
                "description": "For mode='map': object mapping role names to existing Trello list IDs. Roles: ideas, planning, blocked_plan, backlog, in_progress, blocked_work, done."
            }
        },
        "required": []
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle setup_trello_board tool call."""
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
            text="Error: No board selected. Use configure_trello with board_id first."
        )]

    mode = arguments.get("mode", "auto")

    if mode == "map":
        return await _handle_map_mode(arguments, board_id)

    return await _handle_auto_mode(board_id)


async def _handle_auto_mode(board_id: str) -> list[TextContent]:
    """Auto-match lists by name, create missing ones."""
    try:
        existing_lists = await trello_request(
            "GET", f"/boards/{board_id}/lists",
            params={"fields": "name,id"}
        )
    except Exception as e:
        return [TextContent(type="text", text=f"Error fetching lists: {e}")]

    # Build name -> id lookup (case-insensitive)
    list_lookup = {lst["name"].lower(): lst for lst in existing_lists}

    lane_map = {}
    created = []
    matched = []

    for role, expected_name in LANE_NAMES.items():
        existing = list_lookup.get(expected_name.lower())
        if existing:
            lane_map[role] = existing["id"]
            matched.append(f"  {role} -> {existing['name']} (existing)")
        else:
            # Create the list
            try:
                new_list = await trello_request(
                    "POST", "/lists",
                    params={"name": expected_name, "idBoard": board_id, "pos": "bottom"}
                )
                lane_map[role] = new_list["id"]
                created.append(f"  {role} -> {expected_name} (created)")
            except Exception as e:
                return [TextContent(type="text", text=f"Error creating list '{expected_name}': {e}")]

    # Labels
    try:
        existing_labels = await trello_request(
            "GET", f"/boards/{board_id}/labels",
            params={"fields": "name,id,color"}
        )
    except Exception as e:
        return [TextContent(type="text", text=f"Error fetching labels: {e}")]

    label_lookup = {lbl["name"].lower(): lbl for lbl in existing_labels if lbl.get("name")}

    label_map = {}
    labels_created = []
    labels_matched = []

    for name, color in LABEL_DEFS.items():
        existing = label_lookup.get(name.lower())
        if existing:
            label_map[name] = existing["id"]
            labels_matched.append(f"  {name} ({existing.get('color', 'no color')}) (existing)")
        else:
            try:
                new_label = await trello_request(
                    "POST", f"/boards/{board_id}/labels",
                    params={"name": name, "color": color}
                )
                label_map[name] = new_label["id"]
                labels_created.append(f"  {name} ({color}) (created)")
            except Exception as e:
                return [TextContent(type="text", text=f"Error creating label '{name}': {e}")]

    # Save mappings
    tc = get_trello_config()
    tc["lane_map"] = lane_map
    tc["label_map"] = label_map
    save_trello_config(tc)

    # Report
    lines = ["Board setup complete!", ""]
    lines.append("Lanes:")
    lines.extend(matched + created)
    lines.append("")
    lines.append("Labels:")
    lines.extend(labels_matched + labels_created)
    lines.append("")
    lines.append(f"Matched: {len(matched)} lanes, {len(labels_matched)} labels")
    lines.append(f"Created: {len(created)} lanes, {len(labels_created)} labels")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_map_mode(arguments: dict, board_id: str) -> list[TextContent]:
    """Manually map existing lists to roles."""
    lane_assignments = arguments.get("lane_assignments")

    if not lane_assignments:
        # Show existing lists so user can map them
        try:
            existing_lists = await trello_request(
                "GET", f"/boards/{board_id}/lists",
                params={"fields": "name,id"}
            )
        except Exception as e:
            return [TextContent(type="text", text=f"Error fetching lists: {e}")]

        lines = [
            "Manual mapping mode. Existing lists on this board:",
            "",
        ]
        for lst in existing_lists:
            lines.append(f"  - {lst['name']}: {lst['id']}")

        lines.append("")
        lines.append("Expected roles: " + ", ".join(LANE_NAMES.keys()))
        lines.append("")
        lines.append("Call setup_trello_board with mode='map' and lane_assignments mapping roles to list IDs.")
        lines.append('Example: {"backlog": "list_id_1", "in_progress": "list_id_2", ...}')

        return [TextContent(type="text", text="\n".join(lines))]

    # Validate roles
    invalid = [r for r in lane_assignments if r not in LANE_NAMES]
    if invalid:
        return [TextContent(
            type="text",
            text=f"Error: Unknown roles: {', '.join(invalid)}\nValid roles: {', '.join(LANE_NAMES.keys())}"
        )]

    # Save lane map
    tc = get_trello_config()
    tc["lane_map"] = lane_assignments
    save_trello_config(tc)

    # Also auto-setup labels
    try:
        existing_labels = await trello_request(
            "GET", f"/boards/{board_id}/labels",
            params={"fields": "name,id,color"}
        )
    except Exception as e:
        return [TextContent(type="text", text=f"Error fetching labels: {e}")]

    label_lookup = {lbl["name"].lower(): lbl for lbl in existing_labels if lbl.get("name")}
    label_map = {}

    for name, color in LABEL_DEFS.items():
        existing = label_lookup.get(name.lower())
        if existing:
            label_map[name] = existing["id"]
        else:
            try:
                new_label = await trello_request(
                    "POST", f"/boards/{board_id}/labels",
                    params={"name": name, "color": color}
                )
                label_map[name] = new_label["id"]
            except Exception as e:
                return [TextContent(type="text", text=f"Error creating label '{name}': {e}")]

    tc = get_trello_config()
    tc["label_map"] = label_map
    save_trello_config(tc)

    lines = [
        "Manual lane mapping saved!",
        "",
        "Lanes:",
    ]
    for role, list_id in lane_assignments.items():
        lines.append(f"  {role} -> {list_id}")
    lines.append("")
    lines.append(f"Labels: {len(label_map)} configured")

    return [TextContent(type="text", text="\n".join(lines))]
