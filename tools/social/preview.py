"""
Social media preview — resolve media, optimize images, generate HTML preview, save draft.
"""

import base64
import json
import os
import tempfile
import webbrowser
from io import BytesIO
from pathlib import Path

from mcp.types import Tool, TextContent

from utils import find_main_lua


TOOL = Tool(
    name="preview_social_post",
    description="Generate an HTML preview of a social media post showing how it will appear on each platform (Twitter/Facebook card mockups). Opens in browser. Must preview before publishing. Supports attaching a simulator screenshot.\n\nIMPORTANT: Before calling this tool, help the user craft compelling post content. Run `git log --oneline --since='1 week ago'` to review recent development activity. Summarize the key changes into 2-3 draft post options with different tones (casual/excited, professional, community-focused). Suggest relevant hashtags based on the project and changes. Let the user pick or refine a draft before previewing. Also check for available screenshots to attach using get_simulator_screenshot or list_screenshots.",
    inputSchema={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The text content of the post"
            },
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Platforms to post to (e.g. ['twitter', 'facebook']). Must match accounts connected in Late."
            },
            "media": {
                "type": "string",
                "description": "Screenshot to attach: 'latest', 'last', a number, or a file path. Uses same conventions as get_simulator_screenshot."
            },
            "project_path": {
                "type": "string",
                "description": "Path to Solar2D project (needed if media is 'latest', 'last', or a number)"
            },
            "title": {
                "type": "string",
                "description": "Optional title (used for Reddit posts)"
            },
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Hashtags to append (without # prefix)"
            },
            "subreddit": {
                "type": "string",
                "description": "Subreddit to post to (for Reddit, without r/ prefix)"
            }
        },
        "required": ["content", "platforms"]
    }
)

# Platform image specs: (width, height, max_bytes, notes)
PLATFORM_IMAGE_SPECS = {
    "twitter":   (1200, 675,  5 * 1024 * 1024, "16:9 landscape"),
    "facebook":  (1200, 630, 10 * 1024 * 1024, "~1.91:1 landscape"),
    "instagram": (1080, 1080, 8 * 1024 * 1024, "1:1 square, JPEG only"),
    "reddit":    (None, None, 20 * 1024 * 1024, "Original size"),
    "linkedin":  (1200, 627, 10 * 1024 * 1024, "~1.91:1 landscape"),
}

# Platform character limits
PLATFORM_CHAR_LIMITS = {
    "twitter": 280,
    "facebook": 63206,
    "instagram": 2200,
    "reddit": 300,  # title limit
    "linkedin": 3000,
    "threads": 500,
    "bluesky": 300,
    "mastodon": 500,
    "tiktok": 2200,
    "youtube": 5000,
    "pinterest": 500,
}

DRAFT_FILE = os.path.join(tempfile.gettempdir(), "solar2d_social_draft.json")


def _resolve_media_path(media: str, project_path: str | None) -> str | None:
    """Resolve media reference to a file path, using same conventions as screenshot.py."""
    if not media:
        return None

    # Direct file path
    if os.path.isfile(media):
        return media

    # Needs project_path for screenshot references
    if not project_path:
        return None

    try:
        main_lua_path = find_main_lua(project_path)
        project_name = Path(main_lua_path).parent.name
    except Exception:
        return None

    screenshot_dir = os.path.join(tempfile.gettempdir(), f"solar2d_screenshots_{project_name}")
    if not os.path.isdir(screenshot_dir):
        return None

    if media == "latest":
        path = os.path.join(screenshot_dir, "screenshot_latest.jpg")
        return path if os.path.isfile(path) else None
    elif media == "last":
        screenshots = sorted([
            f for f in os.listdir(screenshot_dir)
            if f.startswith("screenshot_") and f.endswith(".jpg") and f != "screenshot_latest.jpg"
        ])
        if screenshots:
            return os.path.join(screenshot_dir, screenshots[-1])
        return None
    else:
        try:
            num = int(media)
            path = os.path.join(screenshot_dir, f"screenshot_{num:03d}.jpg")
            return path if os.path.isfile(path) else None
        except ValueError:
            return None


def _optimize_image_for_platform(image_path: str, platform: str) -> str:
    """Resize/crop image for platform. Returns base64 encoded JPEG string."""
    try:
        from PIL import Image
    except ImportError:
        # No Pillow — just return original as base64
        with open(image_path, 'rb') as f:
            return base64.standard_b64encode(f.read()).decode('utf-8')

    img = Image.open(image_path)

    spec = PLATFORM_IMAGE_SPECS.get(platform)
    if not spec or spec[0] is None:
        # No resize needed (e.g. Reddit) — return original
        with open(image_path, 'rb') as f:
            return base64.standard_b64encode(f.read()).decode('utf-8')

    target_w, target_h, max_size, _ = spec

    # Resize to fit within target dimensions, maintaining aspect ratio via cover crop
    img_w, img_h = img.size
    target_ratio = target_w / target_h
    img_ratio = img_w / img_h

    if img_ratio > target_ratio:
        # Image is wider — fit height, crop width
        new_h = target_h
        new_w = int(img_ratio * target_h)
    else:
        # Image is taller — fit width, crop height
        new_w = target_w
        new_h = int(target_w / img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center crop to exact target
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    # Convert to RGB for JPEG
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    # Encode as JPEG
    buf = BytesIO()
    quality = 92
    img.save(buf, format='JPEG', quality=quality)

    # If too large, reduce quality
    while buf.tell() > max_size and quality > 30:
        buf = BytesIO()
        quality -= 10
        img.save(buf, format='JPEG', quality=quality)

    return base64.standard_b64encode(buf.getvalue()).decode('utf-8')


def _get_platform_css_class(platform: str) -> str:
    """Get CSS class for platform."""
    known = {"twitter", "facebook", "instagram", "reddit", "linkedin",
             "threads", "bluesky", "mastodon", "tiktok", "youtube", "pinterest"}
    return platform if platform in known else "default"


def _build_card_html(platform: str, content: str, image_b64: str | None,
                     title: str | None, hashtags: list[str] | None) -> str:
    """Build HTML for a single platform card."""
    css_class = _get_platform_css_class(platform)
    icon_letter = platform[0].upper()
    display_name = platform.capitalize()

    # Build content with hashtags
    display_content = content
    hashtag_html = ""
    if hashtags:
        tags = " ".join(f"#{tag}" for tag in hashtags)
        hashtag_html = f'<div class="hashtags">{tags}</div>'

    # Character count
    full_text = content
    if hashtags:
        full_text += " " + " ".join(f"#{tag}" for tag in hashtags)

    char_limit = PLATFORM_CHAR_LIMITS.get(platform)
    if platform == "reddit" and title:
        # For Reddit, check title length
        char_count = len(title)
        limit_label = f"{char_count}/{char_limit} (title)"
    else:
        char_count = len(full_text)
        limit_label = f"{char_count}/{char_limit}" if char_limit else f"{char_count} chars"

    count_class = "char-count"
    if char_limit:
        if char_count > char_limit:
            count_class += " error"
        elif char_count > char_limit * 0.9:
            count_class += " warning"

    # Image HTML
    image_html = ""
    if image_b64:
        image_html = f'<img class="card-image {css_class}" src="data:image/jpeg;base64,{image_b64}" alt="Post image">'

    # Title HTML (for Reddit)
    title_html = ""
    if title:
        from html import escape
        title_html = f'<div class="card-title">{escape(title)}</div>'

    from html import escape
    return f'''
    <div class="card">
      <div class="card-header">
        <div class="platform-icon {css_class}">{icon_letter}</div>
        <span class="platform-name">{display_name}</span>
      </div>
      {image_html}
      <div class="card-body">
        {title_html}
        <div class="card-text">{escape(display_content)}</div>
        {hashtag_html}
      </div>
      <div class="card-footer">
        <span class="{count_class}">{limit_label}</span>
        <span>Preview</span>
      </div>
    </div>'''


def _build_warnings(content: str, platforms: list[str], hashtags: list[str] | None,
                    title: str | None) -> list[tuple[str, str]]:
    """Build list of (level, message) warnings."""
    warnings = []
    full_text = content
    if hashtags:
        full_text += " " + " ".join(f"#{tag}" for tag in hashtags)

    for platform in platforms:
        char_limit = PLATFORM_CHAR_LIMITS.get(platform)
        if not char_limit:
            continue

        if platform == "reddit" and title:
            if len(title) > char_limit:
                warnings.append(("error", f"Reddit title exceeds {char_limit} characters ({len(title)} used)"))
        else:
            if len(full_text) > char_limit:
                warnings.append(("error", f"{platform.capitalize()} content exceeds {char_limit} characters ({len(full_text)} used)"))
            elif char_limit <= 300 and len(full_text) > char_limit * 0.9:
                warnings.append(("warning", f"{platform.capitalize()} content is near the {char_limit} character limit ({len(full_text)} used)"))

    if "instagram" in platforms and not hashtags:
        warnings.append(("warning", "Instagram posts perform better with hashtags"))

    return warnings


async def handle(arguments: dict) -> list[TextContent]:
    """Handle preview_social_post tool call."""
    content = arguments.get("content")
    platforms = arguments.get("platforms")
    media = arguments.get("media")
    project_path = arguments.get("project_path")
    title = arguments.get("title")
    hashtags = arguments.get("hashtags")
    subreddit = arguments.get("subreddit")

    if not content:
        return [TextContent(type="text", text="Error: content is required")]
    if not platforms or not isinstance(platforms, list):
        return [TextContent(type="text", text="Error: platforms must be a non-empty list")]

    platforms = [p.lower().strip() for p in platforms]

    # Resolve media
    media_path = None
    if media:
        media_path = _resolve_media_path(media, project_path)
        if media_path is None:
            return [TextContent(
                type="text",
                text=f"Error: Could not resolve media '{media}'. "
                     f"Use 'latest', 'last', a number, or a direct file path. "
                     f"If using screenshot references, provide project_path."
            )]

    # Build optimized images per platform
    platform_images = {}
    if media_path:
        for platform in platforms:
            platform_images[platform] = _optimize_image_for_platform(media_path, platform)

    # Build cards HTML
    cards_html = ""
    for platform in platforms:
        image_b64 = platform_images.get(platform)
        cards_html += _build_card_html(platform, content, image_b64, title, hashtags)

    # Build warnings
    warnings = _build_warnings(content, platforms, hashtags, title)
    warnings_html = ""
    if warnings:
        items = ""
        for level, msg in warnings:
            css = "warning-item error" if level == "error" else "warning-item"
            from html import escape
            items += f'<div class="{css}">{escape(msg)}</div>\n'
        warnings_html = f'<div class="warnings">{items}</div>'

    # Load template
    template_path = os.path.join(os.path.dirname(__file__), "preview_template.html")
    with open(template_path, 'r') as f:
        html = f.read()

    html = html.replace("{{CARDS}}", cards_html)
    html = html.replace("{{WARNINGS}}", warnings_html)

    # Write HTML preview to temp file and open
    preview_path = os.path.join(tempfile.gettempdir(), "solar2d_social_preview.html")
    with open(preview_path, 'w') as f:
        f.write(html)

    webbrowser.open(f"file://{preview_path}")

    # Save draft
    draft = {
        "content": content,
        "platforms": platforms,
        "media_path": media_path,
        "title": title,
        "hashtags": hashtags,
        "subreddit": subreddit,
    }
    with open(DRAFT_FILE, 'w') as f:
        json.dump(draft, f, indent=2)

    # Build summary
    summary_lines = [
        "Preview opened in browser!",
        "",
        f"Platforms: {', '.join(platforms)}",
        f"Content: {content[:80]}{'...' if len(content) > 80 else ''}",
    ]
    if media_path:
        summary_lines.append(f"Media: {media_path}")
    if title:
        summary_lines.append(f"Title: {title}")
    if hashtags:
        summary_lines.append(f"Hashtags: {' '.join(f'#{t}' for t in hashtags)}")
    if subreddit:
        summary_lines.append(f"Subreddit: r/{subreddit}")

    summary_lines.append("")
    summary_lines.append(f"Draft saved to {DRAFT_FILE}")
    summary_lines.append("")

    if warnings:
        summary_lines.append("Warnings:")
        for level, msg in warnings:
            prefix = "ERROR" if level == "error" else "WARN"
            summary_lines.append(f"  [{prefix}] {msg}")
        summary_lines.append("")

    summary_lines.append("Review the preview, then:")
    summary_lines.append("  - Tell me to publish it (uses publish_social_post)")
    summary_lines.append("  - Tell me to schedule it for a specific time")
    summary_lines.append("  - Ask me to make changes and re-preview")

    return [TextContent(type="text", text="\n".join(summary_lines))]
