"""
Art generation tools — create images from a prompt, or edit / restyle existing images.

Two providers: OpenAI GPT Image models and Black Forest Labs FLUX models.
"""

import asyncio
import mimetypes
from pathlib import Path

from mcp.types import ImageContent, TextContent, Tool

from tools.art import bfl, cutout
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
        "description": (
            "transparent for sprites, icons and UI pieces. openai: native alpha (png or webp). bfl has no alpha output, so "
            "the art is drawn on flat magenta and the background is removed locally (see cutout); output is always png."
        )
    },
    "cutout": {
        "type": "string",
        "enum": ["auto", "chroma", "vision", "difference"],
        "description": (
            "bfl + transparent: how the background is removed. chroma keys out flat magenta (crisp pixel-art edges, one "
            "render), vision uses Apple's subject cutout, auto (default) uses chroma when the border is flat. difference "
            "renders on white, then edits that render onto black, and computes real partial alpha from the pair: use it for "
            "glows, sparkles, smoke, glass and soft shadows. Costs two renders per image. difference uses flux-2-pro "
            "unless a model is passed."
        )
    },
    "keep_shadows": {
        "type": "boolean",
        "description": "bfl + transparent (chroma): turn a cast shadow drawn on the background into a soft black shadow (default true) or remove it."
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

REMOVE_BACKGROUND_TOOL = Tool(
    name="remove_background",
    description=(
        "Make an image's background transparent, locally and for free: existing sprites, art from any provider, "
        "screenshots. chroma removes a flat background colour (crisp edges, also clears enclosed gaps); vision uses "
        "Apple's on-device subject cutout for painted or busy backgrounds (macOS 14+); auto picks chroma when the "
        "border is one flat colour; difference computes real partial alpha from the same art on white (image) and on "
        "black (black_image). Writes a PNG with alpha and returns a preview."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "image": {"type": "string", "description": "Path to the image."},
            "method": {
                "type": "string",
                "enum": ["auto", "chroma", "vision", "difference"],
                "description": "Default auto. difference: image is the art on white, black_image the same art on black."
            },
            "black_image": {
                "type": "string",
                "description": "difference: path to the same art rendered on pure black (image must be the one on white)."
            },
            "key_color": {
                "type": "string",
                "description": "chroma: background colour to remove as #RRGGBB (default: detected from the border)."
            },
            "tolerance": {
                "type": "integer",
                "minimum": 0,
                "maximum": 255,
                "description": f"chroma: how far from the key colour still counts as background (default {cutout.TOLERANCE}). Raise for JPEG noise, lower if the subject is eaten."
            },
            "keep_shadows": {
                "type": "boolean",
                "description": "chroma: turn a shadow drawn on the background colour into a soft black shadow (default true) or remove it."
            },
            "save_to": {
                "type": "string",
                "description": "Output PNG path (default: <image name>-transparent.png next to the source)."
            },
        },
        "required": ["image"],
    },
)

TOOLS = [GENERATE_TOOL, EDIT_TOOL, REMOVE_BACKGROUND_TOOL]

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
    if arguments.get("background") == "transparent" and arguments.get("output_format") == "jpeg":
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


def _save_and_report(images: list[bytes], arguments: dict, header: str, notes: list[str],
                     originals: list[dict[str, bytes]] | None = None) -> list[TextContent | ImageContent]:
    """
    Write images and report them. originals (local cutouts): per image, {suffix: bytes} of the renders
    before cutout, written as <name>-<suffix>.<ext>.
    """
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
    if originals:
        # Kept so a cutout can be redone with remove_background without paying for a new image.
        kept = []
        for renders, path in zip(originals, paths):
            for suffix, data in renders.items():
                original = path.with_name(f"{path.stem}-{suffix}.{sniff_ext(data)}")
                original.write_bytes(data)
                kept.append(original)
        lines.append("  Before cutout: " + ", ".join(str(k) for k in kept))
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

DIFFERENCE_MODEL = "flux-2-pro"  # cutout=difference default, whatever bfl_default_model is

async def _bfl_run(arguments: dict, references: list[bytes], verb: str) -> list[TextContent | ImageContent]:
    n = int(arguments.get("n") or 1)
    seed = arguments.get("seed")
    transparent = arguments.get("background") == "transparent"
    method = arguments.get("cutout") or "auto"
    if transparent and method == "difference":
        # flux-2-pro follows the black edit reliably; the configured default may not (flux-3-image).
        model = arguments.get("model") or DIFFERENCE_MODEL
        return await _bfl_difference(arguments, references, verb, model, n, seed)
    model = arguments.get("model") or bfl.get_default_model()
    prompt = arguments["prompt"]
    output_format = arguments.get("output_format")
    if transparent:
        # BFL has no alpha output: draw on flat magenta, then key it out locally.
        prompt += cutout.KEY_PROMPT
        output_format = "png"  # lossless, so the key colour stays exact (flux-3 picks its own format)
        references = [cutout.flatten_on_key(r) for r in references]
    bodies = []
    for i in range(n):
        # Each BFL task makes one image; offset a fixed seed so variations differ.
        task_seed = seed + i if seed is not None else None
        bodies.append(bfl.build_body(model, prompt, references, arguments.get("size"), task_seed, output_format))
    results = await asyncio.gather(*(bfl.generate(model, body) for body in bodies))
    images = [r[0] for r in results]
    cut_notes = []
    originals: list[dict[str, bytes]] = []
    if transparent:
        originals = [{"original": img} for img in images]
        keep_shadows = arguments.get("keep_shadows", True)
        cut = await asyncio.gather(*(cutout.remove_background(img, method, keep_shadows=keep_shadows) for img in images))
        images = [c[0] for c in cut]
        cut_notes = [f"Background removed: {c[1]}" for c in cut]
    costs = [r[1].get("cost") for r in results if r[1].get("cost") is not None]
    notes = [f"Tasks: {', '.join(str(r[1]['id']) for r in results)} ({max(r[1]['seconds'] for r in results)}s)"]
    if costs:
        notes.append(f"Cost: {sum(costs):g} credits (1 credit = $0.01)")
    if model.startswith("flux-3") and seed is not None:
        notes.append("Note: flux-3 models ignore seed.")
    notes += cut_notes
    return _save_and_report(images, arguments, f"{verb} {len(images)} image(s) with bfl/{model}:", notes, originals)


def _size_of(image: bytes) -> str:
    from io import BytesIO

    from PIL import Image

    w, h = Image.open(BytesIO(image)).size
    return f"{w}x{h}"


async def _bfl_difference(arguments: dict, references: list[bytes], verb: str, model: str, n: int,
                          seed: int | None) -> list[TextContent | ImageContent]:
    """Transparent art from two renders: on white, then the same image edited onto black."""
    white_refs = [cutout.flatten_on_key(r, (255, 255, 255)) for r in references]
    prompt = arguments["prompt"] + cutout.WHITE_PROMPT
    seeds = [seed + i if seed is not None else None for i in range(n)]
    whites = await asyncio.gather(*(
        bfl.generate(model, bfl.build_body(model, prompt, white_refs, arguments.get("size"), s, "png")) for s in seeds))

    async def black_pass(white: bytes, s: int | None) -> tuple[bytes, str, list[dict], bytes]:
        """
        Edit the white render onto black and matte the pair. If the model ignores the edit (flux-3-image
        left the background white in testing), retry once with flux-2-pro, which follows it reliably.
        Returns (black render, description, task infos, matte).
        """
        tried = []
        for m in dict.fromkeys([model, "flux-2-pro"]):
            body = bfl.build_body(m, cutout.BLACK_EDIT_PROMPT, [white], _size_of(white), s, "png")
            black, info = await bfl.generate(m, body)
            tried.append(info)
            matte, how, stats = cutout.difference_matte(white, black)
            if stats["ok"]:
                note = "" if m == model else f" (black pass redone with {m}: {model} did not repaint the background)"
                return black, how + note, tried, matte
        # Neither pass is usable: cut the white render out with Apple Vision instead.
        matte, fallback = await cutout.remove_background(white, "vision")
        return black, (f"black pass unusable ({stats['both_white']:.0%} still white, {stats['mismatch']:.0%} misaligned); "
                       f"used {fallback} on the white render"), tried, matte

    passes = await asyncio.gather(*(black_pass(wr[0], s) for wr, s in zip(whites, seeds)))

    images, originals, cut_notes, black_tasks = [], [], [], []
    for (white, _), (black, how, tried, matte) in zip(whites, passes):
        images.append(matte)
        originals.append({"white": white, "black": black})
        cut_notes.append(f"Background removed: {how}")
        black_tasks += tried

    tasks = [r[1] for r in whites] + black_tasks
    costs = [t["cost"] for t in tasks if t.get("cost") is not None]
    seconds = max(w[1]["seconds"] for w in whites) + sum(t["seconds"] for t in black_tasks) / max(1, n)
    notes = [f"Tasks: {len(tasks)} ({n} on white, then edited onto black; ~{seconds:.0f}s)"]
    if costs:
        notes.append(f"Cost: {sum(costs):g} credits (1 credit = $0.01)")
    notes += cut_notes
    return _save_and_report(images, arguments, f"{verb} {len(images)} image(s) with bfl/{model} (difference matte):",
                            notes, originals)


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


async def handle_remove_background(arguments: dict) -> list[TextContent | ImageContent]:
    source = Path(arguments.get("image") or "").expanduser()
    if not source.is_file():
        return _text(f"Error: image not found: {source}")
    try:
        if arguments.get("method") == "difference":
            black = Path(arguments.get("black_image") or "").expanduser()
            if not black.is_file():
                return _text("Error: method=difference needs black_image: the same art rendered on pure black.")
            data, how, _ = cutout.difference_matte(source.read_bytes(), black.read_bytes())
            return _write_cutout(source, arguments, data, how)
        key = cutout.parse_hex(arguments["key_color"]) if arguments.get("key_color") else None
        data, how = await cutout.remove_background(
            source.read_bytes(), arguments.get("method") or "auto", key, int(arguments.get("tolerance", cutout.TOLERANCE)),
            keep_shadows=arguments.get("keep_shadows", True))
    except Exception as e:
        return _text(f"Error removing background: {e}")

    return _write_cutout(source, arguments, data, how)


def _write_cutout(source: Path, arguments: dict, data: bytes, how: str) -> list[TextContent | ImageContent]:
    target = Path(arguments["save_to"]).expanduser() if arguments.get("save_to") else source.with_name(f"{source.stem}-transparent.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    contents: list[TextContent | ImageContent] = [TextContent(type="text", text=f"Transparent PNG: {target}\n  {how}")]
    shown = preview(data)
    if shown:
        contents.append(ImageContent(type="image", data=shown[0], mimeType=shown[1]))
    return contents
