"""
Art generation tools — sprites, backgrounds and UI art from OpenAI image models.

Optional dependency: install with `pip install 'solar2d-mcp-server[art]'`
(httpx for the API; Pillow for downscaled previews).
"""

from tools.art import configure, generate

TOOLS = [
    configure.TOOL,
    *generate.TOOLS,
]

HANDLERS = {
    "configure_art_generation": configure.handle,
    "generate_art": generate.handle_generate,
    "edit_art": generate.handle_edit,
    "remove_background": generate.handle_remove_background,
}
