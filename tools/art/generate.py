"""
Art generation tools — create images from a prompt, or edit / restyle existing images.

Two providers: OpenAI GPT Image models and Black Forest Labs FLUX models.
"""

import asyncio
import mimetypes
from pathlib import Path

from mcp.types import ImageContent, TextContent, Tool

from tools.art import bfl
from tools.art.client import (
    decode_images,
    get_default_model,
    get_default_provider,
    openai_post_json,
    openai_post_multipart,
    output_paths,
    preview,
    sniff_ext,
    usage_line,
)

PROVIDERS = ("openai", "bfl")

_COMMON_PROPERTIES = {
    "provider": {
        "type": "string",
        "enum": list(PROVIDERS),
        "description": (
            "openai (GPT Image models) or bfl (Black Forest Labs FLUX models). "
            "Default: the configured default provider (openai unless changed)."
        )
    },
    "model": {
        "type": "string",
        "description": (
            "Model for the chosen provider. openai default gpt-image-2.5-sunburst (gpt-image-2.5-flare is faster). "
            "bfl default flux-2-pro; also flux-3-image (newest, up to 10 references), flux-2-max, flux-2-flex, "
            "flux-2-klein-9b (cheap/fast). See configure_art_generation."
        )
    },
    "size": {
        "type": "string",
        "description": (
            "auto (default), 1024x1024, 1536x1024, 1024x1536. gpt-image-2.x models also take any WIDTHxHEIGHT "
            "with both sides divisible by 16, aspect between 1:3 and 3:1, up to 3840x2160 (above 2560x1440 is experimental). "
            "bfl takes any WIDTHxHEIGHT (rounded to multiples of 16; FLUX.2 pro up to 4MP)."
        )
    },
    "quality": {
        "type": "string",
        "enum": ["low", "medium", "high", "xhigh", "max", "auto"],
        "description": "openai only: low is fast and cheap for drafts; high for final art (default: auto). xhigh/max: gpt-image-2.5 models only."
    },
    "background": {
        "type": "string",
        "enum": ["transparent", "opaque", "auto"],
        "description": "openai only: transparent for sprites, icons and UI pieces (needs png or webp). bfl has no transparent output."
    },
    "output_format": {
        "type": "string",
        "enum": ["png", "webp", "jpeg"],
        "description": "File format (default: png for openai; bfl FLUX.2 defaults to jpeg, flux-3 picks its own)."
    },
    "seed": {
        "type": "integer",
        "description": "bfl only (not flux-3): fixed seed to reproduce or nudge a result."
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
        "Generate game art from a text prompt with OpenAI GPT Image or Black Forest Labs FLUX models: sprites, "
        "backgrounds, icons, UI pieces, card art, concept art. Saves full-resolution files and returns a preview of "
        "each. Describe style, palette, framing and camera angle in the prompt; for sprites use provider=openai with "
        "background=transparent. To match existing art, use edit_art with that art as a reference instead."
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
        "Edit existing images, or make new art that matches them, with OpenAI GPT Image or Black Forest Labs FLUX "
        "models. Pass one or more reference images (existing sprites, a simulator screenshot, concept art) and a "
        "prompt such as 'same character, attack pose' or 'remove the background'. openai only: with mask (a PNG whose "
        "transparent area marks what to change), only that region of the first image is redrawn."
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
                "description": "Paths to the reference / source images (png, jpg or webp). openai: up to 16; bfl FLUX.2: up to 8; flux-3: up to 10."
            },
            "mask": {
                "type": "string",
                "description": "openai only: PNG mask for the first image; fully transparent pixels are the area to redraw."
            },
            "input_fidelity": {
                "type": "string",
                "enum": ["high", "low"],
                "description": (
                    "openai only: high keeps faces, logos and details of the references closer (costs more). "
                    "Only gpt-image-1.5 takes high and low, gpt-image-1-mini only low; omit for other models."
                )
            },
            **_COMMON_PROPERTIES,
        },
        "required": ["prompt", "images"],
    },
)

TOOLS = [GENERATE_TOOL, EDIT_TOOL]

_OPENAI_PARAMS = ("size", "quality", "background", "output_format", "n")


def _text(message: str) -> list[TextContent]:
    return [TextContent(type="text", text=message)]


def _check_httpx() -> list[TextContent] | None:
    try:
        import httpx  # noqa: F401
    except ImportError:
        return _text("Error: httpx is not installed. Run: pip install 'solar2d-mcp-server[art]'")
    return None


def _validate(arguments: dict, provider: str) -> str | None:
    if provider not in PROVIDERS:
        return f"Error: provider must be one of {', '.join(PROVIDERS)}."
    if not (arguments.get("prompt") or "").strip():
        return "Error: prompt is required."
    if arguments.get("background") == "transparent":
        if provider == "bfl":
            return "Error: Black Forest Labs models have no transparent output; use provider=openai for transparent sprites."
        if arguments.get("output_format") == "jpeg":
            return "Error: background=transparent needs output_format png or webp."
    if provider == "bfl" and arguments.get("mask"):
        return "Error: mask is openai only; with bfl, describe the region to change in the prompt instead."
    return None


def _resolve_images(arguments: dict) -> tuple[list[Path], Path | None, str | None]:
    image_paths = [Path(p).expanduser() for p in arguments.get("images") or []]
    if not image_paths:
        return [], None, "Error: images needs at least one path."
    mask_path = Path(arguments["mask"]).expanduser() if arguments.get("mask") else None
    absent = [str(p) for p in image_paths if not p.is_file()]
    if mask_path and not mask_path.is_file():
        absent.append(str(mask_path))
    if absent:
        return [], None, "Error: file(s) not found:\n" + "\n".join(f"  {p}" for p in absent)
    return image_paths, mask_path, None


def _save_and_report(images: list[bytes], arguments: dict, header: str, notes: list[str]) -> list[TextContent | ImageContent]:
    if not images:
        return _text("Error: the API returned no images.")
    ext = sniff_ext(images[0])
    paths = output_paths(arguments.get("save_to"), arguments.get("project_path"), arguments["prompt"], len(images), ext)

    contents: list[TextContent | ImageContent] = []
    for data, path in zip(images, paths):
        path.write_bytes(data)
        shown = preview(data)
        if shown:
            contents.append(ImageContent(type="image", data=shown[0], mimeType=shown[1]))

    lines = [header, *[f"  {p}" for p in paths], *[f"  {n}" for n in notes if n]]
    return [TextContent(type="text", text="\n".join(lines)), *contents]


# --- OpenAI -----------------------------------------------------------------------------------

def _openai_notes(response: dict) -> list[str]:
    notes = []
    details = [f"{k}={response[k]}" for k in ("size", "quality", "background") if response.get(k)]
    if details:
        notes.append(", ".join(details))
    notes.append(usage_line(response))
    revised = (response.get("data") or [{}])[0].get("revised_prompt")
    if revised:
        notes.append(f"Revised prompt: {revised}")
    return notes


async def _openai_generate(arguments: dict, verb: str) -> list[TextContent | ImageContent]:
    model = arguments.get("model") or get_default_model(arguments.get("background"))
    payload = {"model": model, "prompt": arguments["prompt"]}
    payload.update({k: arguments[k] for k in _OPENAI_PARAMS if arguments.get(k) is not None})
    response = await openai_post_json("/images/generations", payload)
    images = decode_images(response)
    return _save_and_report(images, arguments, f"{verb} {len(images)} image(s) with openai/{model}:", _openai_notes(response))


async def _openai_edit(arguments: dict, image_paths: list[Path], mask_path: Path | None) -> list[TextContent | ImageContent]:
    model = arguments.get("model") or get_default_model(arguments.get("background"))
    data = {"model": model, "prompt": arguments["prompt"]}
    for k in (*_OPENAI_PARAMS, "input_fidelity"):
        if arguments.get(k) is not None:
            data[k] = str(arguments[k])

    def part(path: Path):
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return (path.name, path.read_bytes(), mime)

    files = [("image[]", part(p)) for p in image_paths]
    if mask_path:
        files.append(("mask", part(mask_path)))
    response = await openai_post_multipart("/images/edits", data, files)
    images = decode_images(response)
    return _save_and_report(images, arguments, f"Edited {len(images)} image(s) with openai/{model}:", _openai_notes(response))


# --- Black Forest Labs ------------------------------------------------------------------------

async def _bfl_run(arguments: dict, references: list[bytes], verb: str) -> list[TextContent | ImageContent]:
    model = arguments.get("model") or bfl.get_default_model()
    n = int(arguments.get("n") or 1)
    seed = arguments.get("seed")
    bodies = []
    for i in range(n):
        # Each BFL task makes one image; offset a fixed seed so variations differ.
        task_seed = seed + i if seed is not None else None
        bodies.append(bfl.build_body(model, arguments["prompt"], references, arguments.get("size"), task_seed,
                                     arguments.get("output_format")))
    results = await asyncio.gather(*(bfl.generate(model, body) for body in bodies))
    images = [r[0] for r in results]
    costs = [r[1].get("cost") for r in results if r[1].get("cost") is not None]
    notes = [f"Tasks: {', '.join(str(r[1]['id']) for r in results)} ({max(r[1]['seconds'] for r in results)}s)"]
    if costs:
        notes.append(f"Cost: {sum(costs):g} credits (1 credit = $0.01)")
    if model.startswith("flux-3") and seed is not None:
        notes.append("Note: flux-3 models ignore seed.")
    return _save_and_report(images, arguments, f"{verb} {len(images)} image(s) with bfl/{model}:", notes)


# --- Handlers ---------------------------------------------------------------------------------

async def handle_generate(arguments: dict) -> list[TextContent | ImageContent]:
    missing = _check_httpx()
    if missing:
        return missing
    provider = arguments.get("provider") or get_default_provider()
    error = _validate(arguments, provider)
    if error:
        return _text(error)
    try:
        if provider == "bfl":
            return await _bfl_run(arguments, [], "Generated")
        return await _openai_generate(arguments, "Generated")
    except Exception as e:
        return _text(f"Error generating art: {e}")


async def handle_edit(arguments: dict) -> list[TextContent | ImageContent]:
    missing = _check_httpx()
    if missing:
        return missing
    provider = arguments.get("provider") or get_default_provider()
    error = _validate(arguments, provider)
    if error:
        return _text(error)
    image_paths, mask_path, error = _resolve_images(arguments)
    if error:
        return _text(error)
    try:
        if provider == "bfl":
            return await _bfl_run(arguments, [p.read_bytes() for p in image_paths], "Edited")
        return await _openai_edit(arguments, image_paths, mask_path)
    except Exception as e:
        return _text(f"Error editing art: {e}")
