"""
Black Forest Labs (FLUX) API client — submit a task, poll it, download the image.

The API key lives in ~/.config/solar2d-mcp/config.json (section "bfl"), never in the
repo. BFL_API_KEY in the environment is used when the config has no key.

Flow (docs.bfl.ai): POST /v1/<model> returns {id, polling_url, cost}; GET polling_url
(with x-key) until status is Ready; download result.sample, a short-lived signed URL
(fetched without x-key). BFL makes one image per task and has no transparent output.
"""

import asyncio
import base64
import time

from config import _load_config, _save_config

API_BASE = "https://api.bfl.ai"
DEFAULT_MODEL = "flux-2-pro"  # BFL: "the recommended default model for image editing and generation"
POLL_TIMEOUT_S = 300.0

_IN_PROGRESS = {"Pending", "Queued", "Reasoning", "Generating"}
_MODERATED = {"Request Moderated", "Content Moderated", "No Card Generated"}


def get_bfl_config() -> dict:
    return _load_config().get("bfl", {})


def save_bfl_config(bfl: dict) -> None:
    config = _load_config()
    config["bfl"] = bfl
    _save_config(config)


def get_api_key() -> str | None:
    import os

    return get_bfl_config().get("api_key") or os.environ.get("BFL_API_KEY")


def get_default_model() -> str:
    return get_bfl_config().get("default_model") or DEFAULT_MODEL


def _headers() -> dict:
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "Black Forest Labs not configured. Call configure_art_generation with bfl_api_key, "
            "or set BFL_API_KEY in the MCP server's environment."
        )
    return {"x-key": key, "accept": "application/json"}


def _api_error(resp) -> RuntimeError:
    try:
        body = resp.json()
        detail = body.get("detail", body)
    except Exception:
        detail = resp.text[:500]
    if resp.status_code == 402:
        return RuntimeError(f"Black Forest Labs 402: out of credits; add some at https://dashboard.bfl.ai ({detail})")
    return RuntimeError(f"Black Forest Labs API {resp.status_code}: {detail}")


async def get_credits() -> float:
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{API_BASE}/v1/credits", headers=_headers())
        if resp.status_code >= 400:
            raise _api_error(resp)
        return float(resp.json().get("credits", 0))


def parse_size(size: str | None) -> tuple[int, int] | None:
    """'1536x1024' -> (1536, 1024), rounded to multiples of 16; None for auto/absent."""
    if not size or size == "auto":
        return None
    try:
        w, h = (int(v) for v in size.lower().split("x"))
    except ValueError:
        raise ValueError(f"size must be WIDTHxHEIGHT or auto, got {size!r}")
    return max(64, round(w / 16) * 16), max(64, round(h / 16) * 16)


def build_body(model: str, prompt: str, images: list[bytes], size: str | None, seed: int | None,
               output_format: str | None) -> dict:
    """
    Request body for a model family. FLUX 3 takes `images` (1-10) and no seed/output_format;
    FLUX.2 / Kontext / 1.1 take input_image, input_image_2 ... plus seed and output_format.
    Reference images go as plain base64.
    """
    body: dict = {"prompt": prompt}
    dims = parse_size(size)
    if dims:
        body["width"], body["height"] = dims
    encoded = [base64.b64encode(img).decode() for img in images]

    if model.startswith("flux-3"):
        if encoded:
            body["images"] = encoded
        return body

    for i, b64 in enumerate(encoded):
        body["input_image" if i == 0 else f"input_image_{i + 1}"] = b64
    if seed is not None:
        body["seed"] = seed
    if output_format in ("png", "jpeg", "webp"):
        body["output_format"] = output_format
    return body


async def generate(model: str, body: dict) -> tuple[bytes, dict]:
    """Run one task to completion. Returns (image bytes, info with id/cost/seconds)."""
    import httpx

    started = time.monotonic()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{API_BASE}/v1/{model}", headers=_headers(), json=body)
        if resp.status_code >= 400:
            raise _api_error(resp)
        task = resp.json()
        polling_url = task.get("polling_url") or f"{API_BASE}/v1/get_result?id={task['id']}"

        delay = 0.5
        while True:
            if time.monotonic() - started > POLL_TIMEOUT_S:
                raise RuntimeError(f"Black Forest Labs task {task.get('id')} still not ready after {POLL_TIMEOUT_S:.0f}s")
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 3.0)
            poll = await client.get(polling_url, headers=_headers())
            try:
                result = poll.json()  # failed tasks can come back as 503 with a JSON body
            except Exception:
                if poll.status_code >= 400:
                    raise _api_error(poll)
                continue
            status = result.get("status")
            if status == "Ready":
                break
            if status in _IN_PROGRESS:
                continue
            if status in _MODERATED:
                reasons = (result.get("details") or {}).get("Moderation Reasons") or []
                raise RuntimeError(f"Black Forest Labs: {status}" + (f" ({', '.join(reasons)})" if reasons else ""))
            raise RuntimeError(f"Black Forest Labs task {task.get('id')}: {status or poll.status_code} {result}")

        sample = (result.get("result") or {}).get("sample")
        if not sample:
            raise RuntimeError(f"Black Forest Labs task {task.get('id')} was Ready without an image: {result}")
        image = await client.get(sample)  # signed URL: no x-key
        image.raise_for_status()

    info = {"id": task.get("id"), "cost": task.get("cost"), "seconds": round(time.monotonic() - started, 1)}
    return image.content, info
