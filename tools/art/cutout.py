"""
Background removal — turn generated art into transparent sprites without a provider that
supports alpha (Black Forest Labs has none).

Three methods:
- difference: two renders of the same art, on white and on black. A pixel's alpha is how little it
  changed between them, and its colour is un-mixed from both; this recovers real partial
  transparency (glows, sparkles, smoke, glass, soft shadows) that keying can only cut or keep.
  Costs a second render. See difference_matte.
- chroma: the art is drawn on a flat key colour (magenta by default); every pixel near that
  colour becomes transparent, with a soft ramp and de-spill at the edges. Keeps hard pixel-art
  edges and also clears enclosed gaps (between arms, inside handles). Pillow only.
- vision: Apple Vision foreground masking (capture/cutout.swift, compiled on first use),
  for painted or photographic art whose background is not flat. macOS 14+.

auto picks chroma when the image border is (nearly) one flat colour, else vision.
"""

import asyncio
import json
import tempfile
from collections import Counter
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CUTOUT_SRC = ROOT / "capture" / "cutout.swift"
CUTOUT_BIN = ROOT / "capture" / ".build" / "cutout"

KEY_COLOR = (255, 0, 255)  # magenta: rare in game art, far from skin, wood, foliage and sky
KEY_PROMPT = (
    " Isolated on a perfectly flat, solid pure magenta (#FF00FF) background filling the whole frame:"
    " no gradient, no texture, no floor, no cast shadow, no other objects, and no magenta or pink in the subject itself."
)

WHITE_PROMPT = (
    " Isolated on a perfectly flat, solid pure white (#FFFFFF) background filling the whole frame:"
    " no gradient, no texture, no floor, no other objects."
)
BLACK_EDIT_PROMPT = (
    "Replace only the white background with perfectly flat, solid pure black (#000000) everywhere white background"
    " shows, including gaps enclosed by the subject. Keep the subject pixel-for-pixel identical: same position, size,"
    " pose, colours, outlines, glow and shading. Do not add, move, recolour or relight anything."
)

# difference_matte: alpha within this of 0/1 snaps to it (render-to-render noise on the subject and background).
SNAP = 0.04
# In a matched pair, white - black is the same in every channel ((1-a)*255). A channel straying this far
# from the pixel's mean difference (or black brighter than white) means the renders don't line up there.
MISMATCH = 40
MAX_MISMATCH = 0.03  # share of such pixels above which the pair is rejected
MAX_BOTH_WHITE = 0.10  # share of pixels white in both renders above which the black pass is deemed to have failed

# Distance is the largest per-channel difference from the key colour (0-255).
TOLERANCE = 60      # at or below: fully transparent
SOFTNESS = 40       # ramp from transparent to opaque over this many levels above TOLERANCE
BORDER_FLAT = 0.85  # share of border pixels near one colour for auto to choose chroma


def parse_hex(color: str) -> tuple[int, int, int]:
    c = color.strip().lstrip("#")
    if len(c) != 6:
        raise ValueError(f"key_color must be #RRGGBB, got {color!r}")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _pixels(img) -> list:
    """Flat pixel list (Pillow 12 deprecates getdata for get_flattened_data)."""
    flat = getattr(img, "get_flattened_data", None)
    return list(flat() if flat else img.getdata())


def _distance(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def _border_pixels(img) -> list[tuple[int, int, int]]:
    """Pixels from a 4px frame around the image (sampled)."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    step = max(1, min(w, h) // 256)
    px = rgb.load()
    out = []
    for x in range(0, w, step):
        for y in (0, 1, 2, 3, h - 4, h - 3, h - 2, h - 1):
            out.append(px[x, y])
    for y in range(0, h, step):
        for x in (0, 1, 2, 3, w - 4, w - 3, w - 2, w - 1):
            out.append(px[x, y])
    return out


def detect_flat_background(img, preferred: tuple[int, int, int] | None = KEY_COLOR) -> tuple[int, int, int] | None:
    """The background colour if the border is (nearly) one flat colour, else None."""
    border = _border_pixels(img)
    if preferred is not None:
        if sum(_distance(p, preferred) <= TOLERANCE for p in border) / len(border) >= BORDER_FLAT:
            return preferred
    # The model may have ignored the key colour (e.g. drew on white): key out whatever flat colour it used.
    quantised = Counter((p[0] // 8 * 8 + 4, p[1] // 8 * 8 + 4, p[2] // 8 * 8 + 4) for p in border)
    candidate = quantised.most_common(1)[0][0]
    near = [p for p in border if _distance(p, candidate) <= TOLERANCE // 2]
    if len(near) / len(border) < BORDER_FLAT:
        return None
    return tuple(sorted(c)[len(c) // 2] for c in zip(*near))  # per-channel median


def chroma_key(img, key: tuple[int, int, int], tolerance: int = TOLERANCE, softness: int = SOFTNESS,
               keep_shadows: bool = True):
    """RGBA image with pixels near `key` made transparent and key-colour spill removed from edges."""
    from PIL import Image, ImageChops

    rgb = img.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, key))
    r, g, b = diff.split()
    dist = ImageChops.lighter(ImageChops.lighter(r, g), b)

    def ramp(d: int) -> int:
        if d <= tolerance:
            return 0
        if d >= tolerance + softness:
            return 255
        return round((d - tolerance) * 255 / softness)

    alpha = dist.point(ramp)
    if img.mode in ("RGBA", "LA"):
        alpha = ImageChops.darker(alpha, img.getchannel("A"))

    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    _shadows_to_alpha(out, key, keep_shadows)
    out = _despill(out, key)
    return _clear_hidden_colour(out)


def _clear_hidden_colour(img):
    """Zero the RGB of fully transparent pixels, so texture filtering in the game can't bleed key colour into edges."""
    from PIL import Image

    clear = Image.new("RGBA", img.size, (0, 0, 0, 0))
    visible = img.getchannel("A").point(lambda a: 255 if a else 0)
    return Image.composite(img, clear, visible)


SHADOW_RESIDUAL = 32  # how far (per channel) a pixel may stray from a darkened key colour and still be shadow


def _shadows_to_alpha(img, key: tuple[int, int, int], keep: bool) -> None:
    """
    Models often draw a cast shadow on the key colour anyway: a darker key colour, t * key with
    0 < t < 1. Turn those pixels into black at alpha (1 - t), a real shadow that sits right on any
    background, or clear them when keep is False. Black and near-black outlines (t ~ 0) are untouched.
    """
    kk = sum(k * k for k in key)
    if kk == 0:
        return
    w, h = img.size
    data = _pixels(img)

    # Pixels that look like a darkened key colour, with their t.
    shade: dict[int, float] = {}
    for idx, (r, g, b, a) in enumerate(data):
        if a == 0:
            continue
        t = (r * key[0] + g * key[1] + b * key[2]) / kk
        if 0.15 <= t <= 1.0 and max(abs(r - t * key[0]), abs(g - t * key[1]), abs(b - t * key[2])) <= SHADOW_RESIDUAL:
            shade[idx] = t

    # Only shade connected to the cleared background is a cast shadow. Shaded parts of the subject
    # (a side panel tinted by reflected key light) are walled off by its outline and stay as drawn.
    def neighbours(i: int):
        x, y = i % w, i // w
        if x > 0:
            yield i - 1
        if x < w - 1:
            yield i + 1
        if y > 0:
            yield i - w
        if y < h - 1:
            yield i + w

    queue = [i for i in shade if any(data[n][3] == 0 for n in neighbours(i))]
    seen = set(queue)
    while queue:
        i = queue.pop()
        for n in neighbours(i):
            if n in shade and n not in seen:
                seen.add(n)
                queue.append(n)

    px = img.load()
    for i in seen:
        a = data[i][3]
        shadow_alpha = round((1 - shade[i]) * 255) if keep else 0
        px[i % w, i // w] = (0, 0, 0, min(a, shadow_alpha))


def _despill(img, key: tuple[int, int, int], band: int = 2):
    """
    Remove the key colour's tint from the edge band: semi-transparent pixels plus opaque pixels
    within `band` px of transparency (outlines the model blended into the background, JPEG fringes).

    Each pixel is treated as subject + s * (key hue); s is the largest amount that keeps every
    key-strong channel at or above the key-weak ones, and is subtracted. Colours without the key's
    hue (gold, wood, foliage for a magenta key) have s = 0 and are untouched.
    """
    from PIL import ImageFilter

    hi = [i for i in range(3) if key[i] >= 128]  # channels the key colour is strong in
    lo = [i for i in range(3) if key[i] < 128]
    if not hi or not lo:
        return img  # grey/white/black keys have no hue to remove
    key_base = max(key[i] for i in lo)
    hue = {i: key[i] - key_base for i in hi}

    alpha = img.getchannel("A")
    near_clear = alpha.filter(ImageFilter.MinFilter(2 * band + 1))  # < 255 where transparency is within `band`
    px = img.load()
    w = img.size[0]
    for idx, (a, m) in enumerate(zip(_pixels(alpha), _pixels(near_clear))):
        if a == 0 or m == 255:
            continue
        x, y = idx % w, idx // w
        r, g, b, _ = px[x, y]
        c = [r, g, b]
        base = max(c[i] for i in lo)
        s = min((c[i] - base) / hue[i] for i in hi)
        if s > 0:
            for i in hi:
                c[i] = round(c[i] - s * hue[i])
            px[x, y] = (c[0], c[1], c[2], a)
    return img


async def _ensure_cutout_binary() -> str | None:
    """Compile capture/cutout.swift if needed. Returns an error string or None."""
    if CUTOUT_BIN.exists() and CUTOUT_BIN.stat().st_mtime >= CUTOUT_SRC.stat().st_mtime:
        return None
    from tools.video import _find_tool

    swiftc = _find_tool("swiftc")
    if not swiftc:
        return "swiftc not found: install the Xcode command line tools (xcode-select --install)."
    CUTOUT_BIN.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        swiftc, "-O", "-o", str(CUTOUT_BIN), str(CUTOUT_SRC),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        return "cutout failed to compile:\n" + err.decode(errors="replace")[-2000:]
    return None


async def vision_cutout(image_bytes: bytes):
    """RGBA image of the foreground subject(s) via Apple Vision."""
    from PIL import Image

    err = await _ensure_cutout_binary()
    if err:
        raise RuntimeError(err)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.png", Path(tmp) / "out.png"
        Image.open(BytesIO(image_bytes)).convert("RGB").save(src)
        proc = await asyncio.create_subprocess_exec(
            str(CUTOUT_BIN), str(src), str(dst),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError("Vision cutout: " + err_bytes.decode(errors="replace").strip())
        json.loads(out.decode() or "{}")
        return Image.open(dst).convert("RGBA").copy()


async def remove_background(image_bytes: bytes, method: str = "auto", key: tuple[int, int, int] | None = None,
                            tolerance: int = TOLERANCE, keep_shadows: bool = True) -> tuple[bytes, str]:
    """
    Transparent PNG bytes and a description of what was done.
    method: auto | chroma | vision. key: colour to remove for chroma (default: magenta, else
    the detected flat border colour).
    """
    from PIL import Image

    img = Image.open(BytesIO(image_bytes))
    img.load()

    if method in ("auto", "chroma"):
        bg = key if (method == "chroma" and key) else detect_flat_background(img, key or KEY_COLOR)
        if bg is None and method == "chroma":
            raise RuntimeError("chroma: the border is not one flat colour; pass key_color or use method=vision")
        if bg is not None:
            result = chroma_key(img, bg, tolerance, keep_shadows=keep_shadows)
            how = f"chroma key #{bg[0]:02X}{bg[1]:02X}{bg[2]:02X}"
        else:
            result = await vision_cutout(image_bytes)
            how = "Apple Vision subject cutout (background was not flat)"
    elif method == "vision":
        result = await vision_cutout(image_bytes)
        how = "Apple Vision subject cutout"
    else:
        raise ValueError("method must be auto, chroma or vision")

    alpha = result.getchannel("A")
    clear = alpha.histogram()[0] / (alpha.size[0] * alpha.size[1])
    buf = BytesIO()
    result.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), f"{how}; {clear:.0%} of pixels transparent"


def flatten_on_key(image_bytes: bytes, key: tuple[int, int, int] = KEY_COLOR) -> bytes:
    """Composite a transparent reference onto the key colour, so the model sees the convention."""
    from PIL import Image

    img = Image.open(BytesIO(image_bytes))
    if img.mode not in ("RGBA", "LA", "P") or (img.mode == "P" and "transparency" not in img.info):
        return image_bytes
    rgba = img.convert("RGBA")
    base = Image.new("RGBA", rgba.size, key + (255,))
    base.alpha_composite(rgba)
    buf = BytesIO()
    base.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def difference_matte(white_bytes: bytes, black_bytes: bytes) -> tuple[bytes, str, dict]:
    """
    Alpha from a white-background and a black-background render of the same art.

    Composited over white, a pixel is a*F + (1-a)*255; over black it is a*F. So
    white - black = (1-a)*255, i.e. a = 1 - (white - black)/255 (averaged over channels),
    and F is un-mixed from both renders. Returns (PNG bytes, description, stats).
    stats["mismatch"] is the share of pixels whose white-black difference is not the same in every
    channel (or negative), which only happens where the second render moved or changed the subject;
    stats["both_white"] is the share left white in the black render (background it didn't repaint);
    stats["ok"] is False when either is too high for the matte to be trusted.
    """
    from PIL import Image

    white = Image.open(BytesIO(white_bytes)).convert("RGB")
    black = Image.open(BytesIO(black_bytes)).convert("RGB")
    resized = black.size != white.size
    if resized:
        black = black.resize(white.size, Image.LANCZOS)

    out = []
    mismatched = both_white = 0
    for (wr, wg, wb), (br, bg, bb) in zip(_pixels(white), _pixels(black)):
        dr, dg, db = wr - br, wg - bg, wb - bb
        mean = (dr + dg + db) / 3
        if min(dr, dg, db) < -MISMATCH or max(abs(dr - mean), abs(dg - mean), abs(db - mean)) > MISMATCH:
            mismatched += 1
        if min(wr, wg, wb, br, bg, bb) >= 245:
            both_white += 1
        a = 1 - ((wr - br) + (wg - bg) + (wb - bb)) / (3 * 255)
        if a >= 1 - SNAP:
            a = 1.0
        elif a <= SNAP:
            out.append((0, 0, 0, 0))
            continue
        # Un-mix: from black, F = B/a; from white, F = (W - (1-a)*255)/a. Average the two estimates.
        colour = []
        for w_c, b_c in ((wr, br), (wg, bg), (wb, bb)):
            f = ((b_c / a) + (w_c - (1 - a) * 255) / a) / 2
            colour.append(max(0, min(255, round(f))))
        out.append((colour[0], colour[1], colour[2], round(a * 255)))

    total = white.size[0] * white.size[1]
    result = Image.new("RGBA", white.size)
    putdata = getattr(result, "putdata")
    putdata(out)
    alpha = result.getchannel("A")
    clear = alpha.histogram()[0] / total
    partial = sum(alpha.histogram()[1:255]) / total
    mismatch = mismatched / total

    notes = [f"difference matte; {clear:.0%} transparent, {partial:.1%} semi-transparent"]
    if resized:
        notes.append("black render resized to match")
    if mismatch > 0.002:
        notes.append(f"{mismatch:.1%} of pixels misaligned between renders")
    if both_white / total > 0.005:
        notes.append(f"{both_white / total:.1%} white in both renders (enclosed gaps the black pass didn't repaint?)")

    buf = BytesIO()
    result.save(buf, format="PNG", optimize=True)
    stats = {"mismatch": mismatch, "both_white": both_white / total}
    stats["ok"] = mismatch <= MAX_MISMATCH and stats["both_white"] <= MAX_BOTH_WHITE
    return buf.getvalue(), "; ".join(notes), stats
