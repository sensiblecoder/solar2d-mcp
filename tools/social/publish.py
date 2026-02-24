"""
Social media publish — read draft, upload media, post/schedule via Late API.
"""

import json
import os
import tempfile

from mcp.types import Tool, TextContent

from config import _load_config


TOOL = Tool(
    name="publish_social_post",
    description="Publish or schedule a previously previewed social media post via Late. Requires a saved draft from preview_social_post. Optionally schedule for a future time.",
    inputSchema={
        "type": "object",
        "properties": {
            "schedule_for": {
                "type": "string",
                "description": "Optional ISO 8601 datetime to schedule the post (e.g. '2025-01-15T14:00:00'). If omitted, publishes immediately."
            },
            "timezone": {
                "type": "string",
                "description": "Timezone for scheduled post (default: 'UTC'). E.g. 'America/New_York', 'Europe/London'.",
                "default": "UTC"
            }
        },
        "required": []
    }
)

DRAFT_FILE = os.path.join(tempfile.gettempdir(), "solar2d_social_draft.json")
LATE_API_BASE = "https://getlate.dev/api/v1"


def _get_api_key() -> str | None:
    """Get Late API key from config."""
    config = _load_config()
    return config.get("social", {}).get("late_api_key")


def _load_draft() -> dict | None:
    """Load the saved draft from preview."""
    if not os.path.isfile(DRAFT_FILE):
        return None
    try:
        with open(DRAFT_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


async def handle(arguments: dict) -> list[TextContent]:
    """Handle publish_social_post tool call."""
    try:
        import httpx
    except ImportError:
        return [TextContent(
            type="text",
            text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[social]'"
        )]

    schedule_for = arguments.get("schedule_for")
    timezone = arguments.get("timezone", "UTC")

    # Check API key
    api_key = _get_api_key()
    if not api_key:
        return [TextContent(
            type="text",
            text="Error: No Late API key configured. Use configure_social_media to set your key."
        )]

    # Load draft
    draft = _load_draft()
    if not draft:
        return [TextContent(
            type="text",
            text="Error: No draft found. Use preview_social_post first to create and review a preview."
        )]

    content = draft.get("content", "")
    platforms = draft.get("platforms", [])
    media_path = draft.get("media_path")
    title = draft.get("title")
    hashtags = draft.get("hashtags")
    subreddit = draft.get("subreddit")

    # Build full post text
    post_text = content
    if hashtags:
        post_text += "\n\n" + " ".join(f"#{tag}" for tag in hashtags)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Get accounts to find IDs for requested platforms
        try:
            resp = await client.get(f"{LATE_API_BASE}/accounts", headers=headers)
            resp.raise_for_status()
            accounts = resp.json()
        except httpx.HTTPStatusError as e:
            return [TextContent(
                type="text",
                text=f"Error fetching Late accounts: {e.response.status_code} — {e.response.text}"
            )]
        except httpx.RequestError as e:
            return [TextContent(type="text", text=f"Error connecting to Late API: {e}")]

        # Match platforms to account IDs
        # Late returns accounts with 'provider' and 'id' fields
        account_map = {}
        if isinstance(accounts, list):
            account_list = accounts
        else:
            account_list = accounts.get("data", accounts.get("accounts", []))

        for acct in account_list:
            provider = acct.get("provider", "").lower()
            if provider in platforms:
                account_map[provider] = acct.get("id")

        missing = [p for p in platforms if p not in account_map]
        if missing:
            available = [a.get("provider", "unknown") for a in account_list]
            return [TextContent(
                type="text",
                text=f"Error: No Late accounts found for: {', '.join(missing)}\n"
                     f"Available accounts: {', '.join(available)}\n"
                     f"Connect missing platforms at https://getlate.dev"
            )]

        # 2. Upload media if present
        media_id = None
        if media_path and os.path.isfile(media_path):
            try:
                with open(media_path, 'rb') as f:
                    file_data = f.read()

                filename = os.path.basename(media_path)
                upload_headers = {
                    "Authorization": f"Bearer {api_key}",
                }
                files = {"file": (filename, file_data, "image/jpeg")}
                resp = await client.post(
                    f"{LATE_API_BASE}/utilities/media",
                    headers=upload_headers,
                    files=files,
                )
                resp.raise_for_status()
                upload_result = resp.json()
                media_id = upload_result.get("id") or upload_result.get("mediaId")
            except httpx.HTTPStatusError as e:
                return [TextContent(
                    type="text",
                    text=f"Error uploading media: {e.response.status_code} — {e.response.text}"
                )]
            except httpx.RequestError as e:
                return [TextContent(type="text", text=f"Error uploading media: {e}")]

        # 3. Create post
        post_data = {
            "content": post_text,
            "accountIds": list(account_map.values()),
        }

        if media_id:
            post_data["mediaIds"] = [media_id]

        if title:
            post_data["title"] = title

        if subreddit:
            post_data["subreddit"] = subreddit

        if schedule_for:
            post_data["scheduledFor"] = schedule_for
            post_data["timezone"] = timezone
        else:
            post_data["publishNow"] = True

        try:
            resp = await client.post(
                f"{LATE_API_BASE}/posts",
                headers=headers,
                json=post_data,
            )
            resp.raise_for_status()
            result = resp.json()
        except httpx.HTTPStatusError as e:
            return [TextContent(
                type="text",
                text=f"Error creating post: {e.response.status_code} — {e.response.text}"
            )]
        except httpx.RequestError as e:
            return [TextContent(type="text", text=f"Error creating post: {e}")]

    # Clean up draft
    try:
        os.remove(DRAFT_FILE)
    except OSError:
        pass

    # Build success message
    if schedule_for:
        msg = f"Post scheduled for {schedule_for} ({timezone})!"
    else:
        msg = "Post published!"

    lines = [
        msg,
        "",
        f"Platforms: {', '.join(platforms)}",
        f"Content: {content[:80]}{'...' if len(content) > 80 else ''}",
    ]
    if media_path:
        lines.append(f"Media: attached")
    if title:
        lines.append(f"Title: {title}")

    post_id = result.get("id") or result.get("postId")
    if post_id:
        lines.append(f"Post ID: {post_id}")

    return [TextContent(type="text", text="\n".join(lines))]
