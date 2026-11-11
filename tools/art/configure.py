"""
Art generation configuration — API keys, default provider and default models for
OpenAI (GPT Image) and Black Forest Labs (FLUX).
"""

from mcp.types import TextContent, Tool

from tools.art import bfl
from tools.art.client import (
    DEFAULT_MODEL,
    DEFAULT_TRANSPARENT_MODEL,
    get_api_key,
    get_default_provider,
    get_openai_config,
    list_image_models,
    mask,
    save_openai_config,
    set_default_provider,
)

TOOL = Tool(
    name="configure_art_generation",
    description=(
        "Configure AI art generation: OpenAI GPT Image models and Black Forest Labs FLUX models. Saves API keys to "
        "the user's ~/.config/solar2d-mcp/config.json (never the project), checks each key (OpenAI: image models it "
        "can use; BFL: credit balance), and sets the default provider. Call with no arguments to see the status."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "default_provider": {
                "type": "string",
                "enum": ["openai", "bfl"],
                "description": "Provider generate_art / edit_art use when a call names none (default openai)."
            },
            "api_key": {
                "type": "string",
                "description": "OpenAI API key from https://platform.openai.com/api-keys"
            },
            "default_model": {
                "type": "string",
                "description": f"OpenAI image model used when a call names none (default: {DEFAULT_MODEL})"
            },
            "organization_id": {
                "type": "string",
                "description": "Optional OpenAI organization ID (org-...) to send requests under. Pass an empty string to clear."
            },
            "project_id": {
                "type": "string",
                "description": "Optional OpenAI project ID (proj_...) to send requests under. Pass an empty string to clear."
            },
            "transparent_model": {
                "type": "string",
                "description": f"OpenAI model for background=transparent when a call names none (default: {DEFAULT_TRANSPARENT_MODEL})"
            },
            "bfl_api_key": {
                "type": "string",
                "description": "Black Forest Labs API key from https://dashboard.bfl.ai"
            },
            "bfl_default_model": {
                "type": "string",
                "description": f"Black Forest Labs model used when a call names none (default: {bfl.DEFAULT_MODEL})"
            }
        },
        "required": []
    }
)


def _save_settings(arguments: dict) -> None:
    oc = get_openai_config()
    changed = False
    for arg, field in (("api_key", "api_key"), ("default_model", "default_model"), ("transparent_model", "transparent_model")):
        if arguments.get(arg):
            oc[field] = arguments[arg]
            changed = True
    for field in ("organization_id", "project_id"):
        if field in arguments:
            value = (arguments[field] or "").strip()
            if value:
                oc[field] = value
            else:
                oc.pop(field, None)
            changed = True
    if changed:
        save_openai_config(oc)

    bc = bfl.get_bfl_config()
    if arguments.get("bfl_api_key") or arguments.get("bfl_default_model"):
        if arguments.get("bfl_api_key"):
            bc["api_key"] = arguments["bfl_api_key"]
        if arguments.get("bfl_default_model"):
            bc["default_model"] = arguments["bfl_default_model"]
        bfl.save_bfl_config(bc)

    if arguments.get("default_provider") in ("openai", "bfl"):
        set_default_provider(arguments["default_provider"])


async def _openai_status() -> list[str]:
    oc = get_openai_config()
    key = get_api_key()
    if not key:
        return ["OpenAI: not configured (api_key, or OPENAI_API_KEY in the environment). Keys: https://platform.openai.com/api-keys"]
    source = "config" if oc.get("api_key") else "OPENAI_API_KEY"
    try:
        models = await list_image_models()
    except Exception as e:
        return [f"OpenAI: key {mask(key)} (from {source}) did not work: {e}"]

    def flag(m: str) -> str:
        return "" if m in models else "  (WARNING: not in this key's model list)"

    model = oc.get("default_model") or DEFAULT_MODEL
    tmodel = oc.get("transparent_model") or DEFAULT_TRANSPARENT_MODEL
    return [
        f"OpenAI: key {mask(key)} (from {source}) works.",
        f"  Default model: {model}{flag(model)}",
        f"  Transparent-background model: {tmodel}{flag(tmodel)}",
        *([f"  Organization: {oc['organization_id']}"] if oc.get("organization_id") else []),
        *([f"  Project: {oc['project_id']}"] if oc.get("project_id") else []),
        "  Image models available to this key:",
        *[f"    - {m}" for m in models],
    ]


async def _bfl_status() -> list[str]:
    key = bfl.get_api_key()
    if not key:
        return ["Black Forest Labs: not configured (bfl_api_key, or BFL_API_KEY in the environment). Keys: https://dashboard.bfl.ai"]
    source = "config" if bfl.get_bfl_config().get("api_key") else "BFL_API_KEY"
    try:
        credits = await bfl.get_credits()
    except Exception as e:
        return [f"Black Forest Labs: key {mask(key)} (from {source}) did not work: {e}"]
    lines = [
        f"Black Forest Labs: key {mask(key)} (from {source}) works.",
        f"  Credits: {credits:g} (= ${credits / 100:.2f})",
        f"  Default model: {bfl.get_default_model()}",
    ]
    if credits <= 0:
        lines.append("  WARNING: no credits; generation will fail with 402 until you add some at https://dashboard.bfl.ai")
    return lines


async def handle(arguments: dict) -> list[TextContent]:
    try:
        import httpx  # noqa: F401
    except ImportError:
        return [TextContent(type="text", text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[art]'")]

    _save_settings(arguments)
    lines = [
        f"Default provider: {get_default_provider()}",
        "",
        *await _openai_status(),
        "",
        *await _bfl_status(),
        "",
        "Use generate_art to create images and edit_art to rework existing ones (provider=openai|bfl).",
    ]
    return [TextContent(type="text", text="\n".join(lines))]
