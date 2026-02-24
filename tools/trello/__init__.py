"""
Trello tools — task coordination via Trello boards.

Optional dependency: install with `pip install 'solar2d-mcp-server[trello]'`
httpx is required for all Trello API calls.
"""

from tools.trello import (
    configure, board_setup, cards_list, card_detail,
    card_create, card_update, card_comment, card_attach,
)


TOOLS = [
    configure.TOOL,
    board_setup.TOOL,
    cards_list.TOOL,
    card_detail.TOOL,
    card_create.TOOL,
    card_update.TOOL,
    card_comment.TOOL,
    card_attach.TOOL,
]

HANDLERS = {
    "configure_trello": configure.handle,
    "setup_trello_board": board_setup.handle,
    "list_trello_cards": cards_list.handle,
    "get_trello_card": card_detail.handle,
    "create_trello_card": card_create.handle,
    "update_trello_card": card_update.handle,
    "comment_trello_card": card_comment.handle,
    "attach_to_trello_card": card_attach.handle,
}
