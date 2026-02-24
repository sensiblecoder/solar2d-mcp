"""
Social media tools — post screenshots and dev updates via Late (getlate.dev).

Optional dependency: install with `pip install 'solar2d-mcp-server[social]'`
Core preview functionality works without optional deps (no image optimization).
httpx is required only for publishing.
"""

from tools.social import configure, preview, publish


TOOLS = [
    configure.TOOL,
    preview.TOOL,
    publish.TOOL,
]

HANDLERS = {
    "configure_social_media": configure.handle,
    "preview_social_post": preview.handle,
    "publish_social_post": publish.handle,
}
