"""
Trello card update — move between lanes, add/remove labels, toggle checklist items.
"""

from mcp.types import Tool, TextContent

from tools.trello.client import (
    resolve_lane_id, resolve_lane_role, get_label_map,
    trello_request, LANE_NAMES, VALID_TRANSITIONS,
)

TOOL = Tool(
    name="update_trello_card",
    description=(
        "Update a Trello card: move between lanes, add/remove labels, "
        "toggle checklist items, update name/description/due date.\n\n"
        "WORKFLOW RULES (enforced):\n"
        "  ideas -> planning -> blocked_plan/backlog\n"
        "  blocked_plan -> planning\n"
        "  backlog -> in_progress -> blocked_work/done\n"
        "  blocked_work -> in_progress\n\n"
        "CRITICAL WORKFLOW GUIDANCE:\n"
        "- When a card in 'planning' has a user comment/CTA that needs a response: "
        "respond via comment_trello_card, then move to blocked_plan. "
        "Do NOT leave it in planning or start implementing.\n"
        "- When you've responded to a user and need their review/approval, "
        "ALWAYS move to blocked_plan or blocked_work — never leave cards waiting "
        "for user input in a non-blocked lane.\n"
        "- Never start coding on a card unless it's in backlog or in_progress.\n"
        "- Moving to blocked_plan or blocked_work requires blocked_reason.\n"
        "- Never leave a card in 'in_progress' without resolution. "
        "If you cannot complete the work, move it to 'blocked_work'.\n\n"
        "Labels: bug, priority, ai-created, needs-screenshot, shareable"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "card_id": {
                "type": "string",
                "description": "The Trello card ID"
            },
            "lane": {
                "type": "string",
                "description": "Move card to this lane"
            },
            "blocked_reason": {
                "type": "string",
                "description": "REQUIRED when moving to blocked_plan or blocked_work. Explains what's blocking progress and what the user needs to do."
            },
            "add_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Labels to add"
            },
            "remove_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Labels to remove"
            },
            "check_item": {
                "type": "string",
                "description": "Name (or substring) of a checklist item to toggle complete/incomplete"
            },
            "name": {
                "type": "string",
                "description": "New card name"
            },
            "description": {
                "type": "string",
                "description": "New card description"
            },
            "due": {
                "type": "string",
                "description": "New due date (ISO 8601) or 'null' to clear"
            }
        },
        "required": ["card_id"]
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle update_trello_card tool call."""
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

    changes = []

    # Move to lane (with transition validation)
    lane = arguments.get("lane")
    blocked_reason = arguments.get("blocked_reason")
    if lane:
        if lane not in LANE_NAMES:
            return [TextContent(
                type="text",
                text=f"Error: Unknown lane '{lane}'. Valid: {', '.join(LANE_NAMES.keys())}"
            )]

        # Require blocked_reason for blocked lanes
        if lane in ("blocked_plan", "blocked_work") and not blocked_reason:
            return [TextContent(
                type="text",
                text=f"Error: blocked_reason is required when moving to {LANE_NAMES[lane]}. "
                     f"Explain what's blocking progress and what the user needs to do."
            )]

        list_id = resolve_lane_id(lane)
        if not list_id:
            return [TextContent(
                type="text",
                text=f"Error: Lane '{lane}' not mapped. Run setup_trello_board first."
            )]

        # Fetch card's current list to validate the transition
        try:
            card_data = await trello_request(
                "GET", f"/cards/{card_id}",
                params={"fields": "idList"}
            )
        except Exception as e:
            return [TextContent(type="text", text=f"Error fetching card: {e}")]

        current_list_id = card_data.get("idList")
        current_role = resolve_lane_role(current_list_id) if current_list_id else None

        if current_role:
            allowed = VALID_TRANSITIONS.get(current_role, [])
            if lane not in allowed:
                allowed_names = [f"{r} ({LANE_NAMES[r]})" for r in allowed] if allowed else ["none — terminal lane"]
                return [TextContent(
                    type="text",
                    text=f"Error: Cannot move from {LANE_NAMES[current_role]} to {LANE_NAMES[lane]}.\n"
                         f"Valid moves from {current_role}: {', '.join(allowed_names)}"
                )]

        try:
            await trello_request("PUT", f"/cards/{card_id}", params={"idList": list_id})
            from_str = f" (from {LANE_NAMES[current_role]})" if current_role else ""
            changes.append(f"Moved to {LANE_NAMES[lane]}{from_str}")
        except Exception as e:
            return [TextContent(type="text", text=f"Error moving card: {e}")]

        # Auto-post blocked_reason as a comment
        if blocked_reason and lane in ("blocked_plan", "blocked_work"):
            try:
                await trello_request(
                    "POST", f"/cards/{card_id}/actions/comments",
                    params={"text": f"**Blocked:** {blocked_reason}"}
                )
                changes.append(f"Blocked reason posted: {blocked_reason}")
            except Exception:
                changes.append(f"Blocked reason (failed to post as comment): {blocked_reason}")

    # Update name/description/due
    update_params = {}
    if arguments.get("name"):
        update_params["name"] = arguments["name"]
    if arguments.get("description") is not None:
        update_params["desc"] = arguments["description"]
    if arguments.get("due"):
        due_val = arguments["due"]
        update_params["due"] = None if due_val == "null" else due_val

    if update_params:
        try:
            await trello_request("PUT", f"/cards/{card_id}", params=update_params)
            if "name" in update_params:
                changes.append(f"Name updated to: {update_params['name']}")
            if "desc" in update_params:
                changes.append("Description updated")
            if "due" in update_params:
                changes.append(f"Due date: {update_params['due'] or 'cleared'}")
        except Exception as e:
            return [TextContent(type="text", text=f"Error updating card: {e}")]

    # Add labels
    label_map = get_label_map()
    add_labels = arguments.get("add_labels", [])
    for label_name in add_labels:
        label_id = label_map.get(label_name)
        if not label_id:
            changes.append(f"Warning: Unknown label '{label_name}', skipped")
            continue
        try:
            await trello_request("POST", f"/cards/{card_id}/idLabels", params={"value": label_id})
            changes.append(f"Added label: {label_name}")
        except Exception:
            changes.append(f"Label '{label_name}' may already be on card")

    # Remove labels
    remove_labels = arguments.get("remove_labels", [])
    for label_name in remove_labels:
        label_id = label_map.get(label_name)
        if not label_id:
            changes.append(f"Warning: Unknown label '{label_name}', skipped")
            continue
        try:
            await trello_request("DELETE", f"/cards/{card_id}/idLabels/{label_id}")
            changes.append(f"Removed label: {label_name}")
        except Exception:
            changes.append(f"Label '{label_name}' may not be on card")

    # Toggle checklist item
    check_item_name = arguments.get("check_item")
    if check_item_name:
        try:
            card_data = await trello_request(
                "GET", f"/cards/{card_id}",
                params={"checklists": "all"}
            )
            toggled = False
            for cl in card_data.get("checklists", []):
                for item in cl.get("checkItems", []):
                    if check_item_name.lower() in item.get("name", "").lower():
                        new_state = "incomplete" if item.get("state") == "complete" else "complete"
                        await trello_request(
                            "PUT",
                            f"/cards/{card_id}/checkItem/{item['id']}",
                            params={"state": new_state}
                        )
                        changes.append(f"Checklist item '{item['name']}' -> {new_state}")
                        toggled = True
                        break
                if toggled:
                    break
            if not toggled:
                changes.append(f"No checklist item matching '{check_item_name}' found")
        except Exception as e:
            changes.append(f"Error toggling checklist item: {e}")

    if not changes:
        return [TextContent(type="text", text="No changes specified. Provide at least one field to update.")]

    return [TextContent(type="text", text=f"Card {card_id} updated:\n" + "\n".join(f"  - {c}" for c in changes))]
