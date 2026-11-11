"""
Art generation tools — create images from a prompt, or edit / restyle existing images.
"""

import mimetypes
from pathlib import Path

from mcp.types import ImageContent, TextContent, Tool

from tools.art.client import (
    decode_images,
    get_default_model,
    openai_post_json,
    openai_post_multipart,
    output_paths,
    preview,
    usage_line,
)

_COMMON_PROPERTIES = {
    "model": {
        "type": "string",
        "description": (
            "Image model (default gpt-image-2.5-sunburst; gpt-image-2.5-flare is the faster sibling). "
            "See configure_art_generation for the models this key can use."
        )
    },
    "size": {
        "type": "string",
        "description": (
            "auto (default), 1024x1024, 1536x1024, 1024x1536. gpt-image-2.x models also take any WIDTHxHEIGHT "
            "with both sides divisible by 16, aspect between 1:3 and 3:1, up to 3840x2160 (above 2560x1440 is experimental)."
        )
    },
    "quality": {
        "type": "string",
        "enum": ["low", "medium", "high", "xhigh", "max", "auto"],
        "description": "low is fast and cheap for drafts; high for final art (default: auto). xhigh/max: gpt-image-2.5 models only."
    },
    "background": {
        "type": "string",
        "enum": ["transparent", "opaque", "auto"],
        "description": "transparent for sprites, icons and UI pieces (needs png or webp output)."
    },
    "output_format": {
        "type": "string",
        "enum": ["png", "webp", "jpeg"],
        "description": "File format (default: png)."
    },
    "n": {
        "type": "integer",
        "minimum": 1,
        "maximum": 4,
        "description": "Number of variations to generate (default 1)."
    },
    "save_to": {
        "type": "string",
        "description": "File or directory to write to, e.g. <project>/images/hero.png. Default: ~/Pictures/solar2d-mcp/<project>/art/"
    },
    "project_path": {
        "type": "string",
        "description": "Solar2D project the art is for; names the default output folder."
    },
}

GENERATE_TOOL = Tool(
    name="generate_art",
    description=(
        "Generate game art from a text prompt with an OpenAI image model: sprites, backgrounds, icons, "
        "UI pieces, card art, concept art. Saves full-resolution files and returns a preview of each. "
        "Describe style, palette, framing and camera angle in the prompt; use background=transparent for "
        "sprites. To match existing art, use edit_art with that art as a reference instead."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "What to draw, in detail."},
            **_COMMON_PROPERTIES,
        },
        "required": ["prompt"],
    },
)

EDIT_TOOL = Tool(
    name="edit_art",
    description=(
        "Edit existing images, or make new art that matches them, with an OpenAI image model. Pass one or more "
        "reference images (existing sprites, a simulator screenshot, concept art) and a prompt such as "
        "'same character, attack pose' or 'remove the background'. With mask (a PNG whose transparent area marks "
        "what to change), only that region of the first image is redrawn."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The change to make, or the new image to draw in the references' style."},
            "images": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 16,
                "description": "Paths to the reference / source images (png, jpg or webp)."
            },
            "mask": {
                "type": "string",
                "description": "Optional PNG mask for the first image: fully transparent pixels are the area to redraw."
            },
            "input_fidelity": {
                "type": "string",
                "enum": ["high", "low"],
                "description": (
                    "high keeps faces, logos and details of the references closer (costs more). "
                    "Only gpt-image-1.5 takes high and low, gpt-image-1-mini only low; omit for other models."
                )
            },
            **_COMMON_PROPERTIES,
        },
        "required": ["prompt", "images"],
    },
)

TOOLS = [GENERATE_TOOL, EDIT_TOOL]

_OPTIONAL_PARAMS = ("size", "quality", "background", "output_format", "n")


def _check_httpx() -> list[TextContent] | None:
    try:
        import httpx  # noqa: F401
    except ImportError:
        return [TextContent(type="text", text="Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[art]'")]
    return None


def _validate(arguments: dict) -> str | None:
    if not (arguments.get("prompt") or "").strip():
        return "Error: prompt is required."
    if arguments.get("background") == "transparent" and arguments.get("output_format") == "jpeg":
        return "Error: background=transparent needs output_format png or webp."
    return None


async def _finish(response: dict, arguments: dict, model: str, verb: str) -> list[TextContent | ImageContent]:
    images = decode_images(response)
    if not images:
        return [TextContent(type="text", text=f"Error: the API returned no images. Response keys: {list(response)}")]

    ext = response.get("output_format") or arguments.get("output_format") or "png"
    paths = output_paths(arguments.get("save_to"), arguments.get("project_path"), arguments["prompt"], len(images), ext)

    contents: list[TextContent | ImageContent] = []
    for data, path in zip(images, paths):
        path.write_bytes(data)
        shown = preview(data)
        if shown:
            contents.append(ImageContent(type="image", data=shown[0], mimeType=shown[1]))

    lines = [f"{verb} {len(images)} image(s) with {model}:"]
    lines += [f"  {p}" for p in paths]
    details = [f"{k}={response[k]}" for k in ("size", "quality", "background") if response.get(k)]
    if details:
        lines.append("  " + ", ".join(details))
    usage = usage_line(response)
    if usage:
        lines.append(f"  {usage}")
    revised = (response.get("data") or [{}])[0].get("revised_prompt")
    if revised:
        lines.append(f"  Revised prompt: {revised}")
    return [TextContent(type="text", text="\n".join(lines)), *contents]


async def handle_generate(arguments: dict) -> list[TextContent | ImageContent]:
    missing = _check_httpx()
    if missing:
        return missing
    error = _validate(arguments)
    if error:
        return [TextContent(type="text", text=error)]

    model = arguments.get("model") or get_default_model(arguments.get("background"))
    payload = {"model": model, "prompt": arguments["prompt"]}
    payload.update({k: arguments[k] for k in _OPTIONAL_PARAMS if arguments.get(k) is not None})

    try:
        response = await openai_post_json("/images/generations", payload)
    except Exception as e:
        return [TextContent(type="text", text=f"Error generating art: {e}")]
    return await _finish(response, arguments, model, "Generated")


async def handle_edit(arguments: dict) -> list[TextContent | ImageContent]:
    missing = _check_httpx()
    if missing:
        return missing
    error = _validate(arguments)
    if error:
        return [TextContent(type="text", text=error)]

    image_paths = [Path(p).expanduser() for p in arguments.get("images") or []]
    if not image_paths:
        return [TextContent(type="text", text="Error: images needs at least one path.")]
    absent = [str(p) for p in image_paths if not p.is_file()]
    mask_path = Path(arguments["mask"]).expanduser() if arguments.get("mask") else None
    if mask_path and not mask_path.is_file():
        absent.append(str(mask_path))
    if absent:
        return [TextContent(type="text", text="Error: file(s) not found:\n" + "\n".join(f"  {p}" for p in absent))]

    model = arguments.get("model") or get_default_model(arguments.get("background"))
    data = {"model": model, "prompt": arguments["prompt"]}
    for k in (*_OPTIONAL_PARAMS, "input_fidelity"):
        if arguments.get(k) is not None:
            data[k] = str(arguments[k])

    def part(path: Path):
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return (path.name, path.read_bytes(), mime)

    files = [("image[]", part(p)) for p in image_paths]
    if mask_path:
        files.append(("mask", part(mask_path)))

    try:
        response = await openai_post_multipart("/images/edits", data, files)
    except Exception as e:
        return [TextContent(type="text", text=f"Error editing art: {e}")]
    return await _finish(response, arguments, model, "Edited")
