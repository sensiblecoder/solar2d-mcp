"""
OpenAI Images API client (plus helpers shared with the Black Forest Labs client) — key lookup, requests, and saving results.

The API key lives in ~/.config/solar2d-mcp/config.json (section "openai"), never in
the repo. OPENAI_API_KEY in the environment is used when the config has no key.
"""

import base64
import os
import re
import time
from pathlib import Path

from config import _load_config, _save_config

API_BASE = "https://api.openai.com/v1"
# gpt-image-2 is deprecated; the API reference names gpt-image-2.5-sunburst/-flare as the
# replacements, and they officially support background=transparent (gpt-image-2 only in preview).
DEFAULT_MODEL = "gpt-image-2.5-sunburst"
DEFAULT_TRANSPARENT_MODEL = DEFAULT_MODEL

# Generated art is kept (it is source material), so it lives under ~/Pictures, not the temp dir.
ART_ROOT = Path.home() / "Pictures" / "solar2d-mcp"

# Image generation routinely takes 30-120s; edits with several references take longer.
TIMEOUT_S = 300.0


def get_openai_config() -> dict:
    """Get the openai section from config, or empty dict."""
    return _load_config().get("openai", {})


def save_openai_config(openai: dict) -> None:
    """Save the openai section back to config."""
    config = _load_config()
    config["openai"] = openai
    _save_config(config)


def get_api_key() -> str | None:
    """Configured key, else OPENAI_API_KEY from the environment."""
    return get_openai_config().get("api_key") or os.environ.get("OPENAI_API_KEY")


def get_default_provider() -> str:
    """openai or bfl, from config["art"]["default_provider"] (default openai)."""
    return _load_config().get("art", {}).get("default_provider") or "openai"


def set_default_provider(provider: str) -> None:
    config = _load_config()
    config.setdefault("art", {})["default_provider"] = provider
    _save_config(config)


def get_default_model(background: str | None = None) -> str:
    """The model for a call that names none; transparent backgrounds need a model that supports them."""
    oc = get_openai_config()
    if background == "transparent":
        return oc.get("transparent_model") or DEFAULT_TRANSPARENT_MODEL
    return oc.get("default_model") or DEFAULT_MODEL


def mask(key: str) -> str:
    return key[:8] + "..." + key[-4:] if len(key) > 16 else "***"


def _auth_headers() -> dict:
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "OpenAI not configured. Call configure_art_generation with api_key, "
            "or set OPENAI_API_KEY in the MCP server's environment."
        )
    headers = {"Authorization": f"Bearer {key}"}
    # Optional: bill/limit against a specific org or project (needed for user keys in several orgs).
    oc = get_openai_config()
    if oc.get("organization_id"):
        headers["OpenAI-Organization"] = oc["organization_id"]
    if oc.get("project_id"):
        headers["OpenAI-Project"] = oc["project_id"]
    return headers


def _raise_for_api_error(resp) -> None:
    """Raise with OpenAI's own error message, which says what was wrong with the request."""
    if resp.status_code < 400:
        return
    try:
        message = resp.json()["error"]["message"]
    except Exception:
        message = resp.text[:500]
    raise RuntimeError(f"OpenAI API {resp.status_code}: {message}")


async def openai_get(path: str) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{API_BASE}{path}", headers=_auth_headers())
        _raise_for_api_error(resp)
        return resp.json()


async def openai_post_json(path: str, payload: dict) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        resp = await client.post(f"{API_BASE}{path}", headers=_auth_headers(), json=payload)
        _raise_for_api_error(resp)
        return resp.json()


async def openai_post_multipart(path: str, data: dict, files: list) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        resp = await client.post(f"{API_BASE}{path}", headers=_auth_headers(), data=data, files=files)
        _raise_for_api_error(resp)
        return resp.json()


async def list_image_models() -> list[str]:
    data = await openai_get("/models")
    return sorted(m["id"] for m in data.get("data", []) if "image" in m["id"] or "dall-e" in m["id"])


def _slug(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "art"


def output_paths(save_to: str | None, project_path: str | None, prompt: str, count: int, ext: str) -> list[Path]:
    """
    Where to write `count` images.

    save_to may be a file (gets -1, -2 ... suffixes when count > 1) or a directory.
    Default: ~/Pictures/solar2d-mcp/<project>/art/<timestamp>-<prompt-slug>.<ext>
    """
    stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(prompt)}"

    if save_to:
        target = Path(save_to).expanduser()
        if target.suffix and not target.is_dir():
            target.parent.mkdir(parents=True, exist_ok=True)
            if count == 1:
                return [target]
            return [target.with_name(f"{target.stem}-{i + 1}{target.suffix}") for i in range(count)]
        directory = target
    else:
        project = Path(project_path).expanduser().resolve().name if project_path else "unsorted"
        directory = ART_ROOT / project / "art"

    directory.mkdir(parents=True, exist_ok=True)
    # Timestamped names collide when two calls with the same prompt finish in the same second: don't overwrite.
    base, k = stem, 1
    while True:
        if count == 1:
            paths = [directory / f"{stem}.{ext}"]
        else:
            paths = [directory / f"{stem}-{i + 1}.{ext}" for i in range(count)]
        if not any(p.exists() for p in paths):
            return paths
        k += 1
        stem = f"{base}_{k}"


def decode_images(response: dict) -> list[bytes]:
    """The image bytes from an Images API response (gpt-image models always return b64_json)."""
    images = []
    for item in response.get("data", []):
        b64 = item.get("b64_json")
        if b64:
            images.append(base64.b64decode(b64))
    return images


def preview(image_bytes: bytes, max_side: int = 768) -> tuple[str, str] | None:
    """
    A downscaled (base64, mime) preview for the assistant to look at, or None.

    Keeps transparency (PNG) so sprite edges can be checked. Without Pillow the
    original is returned when it is small enough to inline.
    """
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        if len(image_bytes) <= 1_500_000:
            return base64.standard_b64encode(image_bytes).decode(), _sniff_mime(image_bytes)
        return None

    img = Image.open(BytesIO(image_bytes))
    img.thumbnail((max_side, max_side))
    buf = BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    else:
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        mime = "image/jpeg"
    return base64.standard_b64encode(buf.getvalue()).decode(), mime


def _sniff_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def sniff_ext(data: bytes) -> str:
    """File extension matching the bytes actually returned (providers may ignore output_format)."""
    return {"image/png": "png", "image/webp": "webp"}.get(_sniff_mime(data), "jpg")


def usage_line(response: dict) -> str:
    usage = response.get("usage") or {}
    if not usage:
        return ""
    return f"Tokens: {usage.get('input_tokens', '?')} in / {usage.get('output_tokens', '?')} out"
