"""
Art generation configuration — save the OpenAI API key and default image model.
"""

from mcp.types import TextContent, Tool

from tools.art.client import (
    DEFAULT_MODEL,
    DEFAULT_TRANSPARENT_MODEL,
    get_api_key,
    get_openai_config,
    list_image_models,
    mask,
    save_openai_config,
)

TOOL = Tool(
    name="configure_art_generation",
    description=(
        "Configure AI art generation (OpenAI image models). Saves the OpenAI API key to the user's "
        "~/.config/solar2d-mcp/config.json (never the project), checks it, and lists the image models "
        "the key can use. Call with no arguments to see the current status."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "description": "OpenAI API key from https://platform.openai.com/api-keys"
            },
            "default_model": {
                "type": "string",
                "description": f"Image model used when a call names none (default: {DEFAULT_MODEL})"
            },
            "transparent_model": {
                "type": "string",
                "description": f"Model used for background=transparent when a call names none (default: {DEFAULT_TRANSPARENT_MODEL})"
            }
        },
        "required": []
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    try:
        import httpx  # noqa: F401
    except ImportError:
        return [TextContent(type="text", text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[art]'")]

    api_key = arguments.get("api_key")
    default_model = arguments.get("default_model")
    transparent_model = arguments.get("transparent_model")

    oc = get_openai_config()
    if api_key:
        oc["api_key"] = api_key
    if default_model:
        oc["default_model"] = default_model
    if transparent_model:
        oc["transparent_model"] = transparent_model
    if api_key or default_model or transparent_model:
        save_openai_config(oc)

    key = get_api_key()
    if not key:
        return [TextContent(
            type="text",
            text="OpenAI not configured.\n\n"
                 "1. Create a key at https://platform.openai.com/api-keys\n"
                 "2. Call configure_art_generation with api_key\n"
                 "   (or set OPENAI_API_KEY in the MCP server's environment)"
        )]

    source = "config" if oc.get("api_key") else "OPENAI_API_KEY environment variable"
    try:
        models = await list_image_models()
    except Exception as e:
        return [TextContent(type="text", text=f"OpenAI key {mask(key)} (from {source}) did not work: {e}")]

    def flag(m: str) -> str:
        return "" if m in models else "  (WARNING: not in this key's model list)"

    model = oc.get("default_model") or DEFAULT_MODEL
    tmodel = oc.get("transparent_model") or DEFAULT_TRANSPARENT_MODEL
    lines = [
        f"OpenAI key {mask(key)} (from {source}) works.",
        f"Default model: {model}{flag(model)}",
        f"Transparent-background model: {tmodel}{flag(tmodel)}",
        "",
        "Image models available to this key:",
        *[f"  - {m}" for m in models],
        "",
        "Use generate_art to create images and edit_art to rework existing ones.",
    ]
    return [TextContent(type="text", text="\n".join(lines))]
