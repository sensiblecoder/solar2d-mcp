"""
Social media configuration — save/retrieve Late API key.
"""

from mcp.types import Tool, TextContent

from config import _load_config, _save_config


TOOL = Tool(
    name="configure_social_media",
    description="Configure social media posting via Late (getlate.dev). Save your Late API key to enable posting screenshots and dev updates to connected platforms.",
    inputSchema={
        "type": "object",
        "properties": {
            "late_api_key": {
                "type": "string",
                "description": "Your Late API key from https://getlate.dev/settings/api"
            }
        },
        "required": []
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle configure_social_media tool call."""
    api_key = arguments.get("late_api_key")

    config = _load_config()
    social = config.get("social", {})

    # If no key provided, show current status
    if not api_key:
        if social.get("late_api_key"):
            masked = social["late_api_key"][:8] + "..." + social["late_api_key"][-4:]
            return [TextContent(
                type="text",
                text=f"Late API key is configured: {masked}\n\n"
                     f"To update, call configure_social_media with a new late_api_key.\n"
                     f"To post, use preview_social_post to create a preview first."
            )]
        else:
            return [TextContent(
                type="text",
                text="No Late API key configured.\n\n"
                     "Get your API key from https://getlate.dev/settings/api\n"
                     "Then call configure_social_media with your late_api_key."
            )]

    # Save the key
    social["late_api_key"] = api_key
    config["social"] = social
    _save_config(config)

    masked = api_key[:8] + "..." + api_key[-4:]
    return [TextContent(
        type="text",
        text=f"Late API key saved: {masked}\n\n"
             f"You can now use preview_social_post to create social media posts.\n"
             f"Make sure you have connected your social accounts at https://getlate.dev"
    )]
