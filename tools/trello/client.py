"""
Trello API client — async httpx wrapper with auth and helper functions.

Shared by all Trello tool modules. Uses query-param auth (?key=...&token=...).
"""

from config import _load_config, _save_config

# Trello API base URL
API_BASE = "https://api.trello.com/1"

# Workflow lane names (role -> expected Trello list name)
LANE_NAMES = {
    "ideas": "Ideas",
    "planning": "Planning",
    "blocked_plan": "Blocked:Plan",
    "backlog": "Backlog",
    "in_progress": "In Progress",
    "blocked_work": "Blocked:Work",
    "done": "Done",
}

# Valid lane transitions — each lane lists where it can move to.
# Enforces the workflow: cards can only advance one step (or go to/from blocked).
VALID_TRANSITIONS = {
    "ideas":        ["planning"],
    "planning":     ["blocked_plan", "backlog"],
    "blocked_plan": ["planning"],
    "backlog":      ["in_progress"],
    "in_progress":  ["blocked_work", "done"],
    "blocked_work": ["in_progress"],
    "done":         [],  # terminal
}

# Label definitions (name -> color)
LABEL_DEFS = {
    "bug": "red",
    "priority": "yellow",
    "ai-created": "purple",
    "needs-screenshot": "orange",
    "shareable": "pink",
}


def get_trello_config() -> dict:
    """Get the trello section from config, or empty dict."""
    config = _load_config()
    return config.get("trello", {})


def save_trello_config(trello: dict) -> None:
    """Save the trello section back to config."""
    config = _load_config()
    config["trello"] = trello
    _save_config(config)


def get_auth_params() -> dict | None:
    """Get Trello auth query params, or None if not configured."""
    tc = get_trello_config()
    api_key = tc.get("api_key")
    api_token = tc.get("api_token")
    if not api_key or not api_token:
        return None
    return {"key": api_key, "token": api_token}


def get_board_id() -> str | None:
    """Get the configured board ID."""
    return get_trello_config().get("board_id")


def get_lane_map() -> dict:
    """Get role -> Trello list ID mapping."""
    return get_trello_config().get("lane_map", {})


def get_label_map() -> dict:
    """Get label name -> Trello label ID mapping."""
    return get_trello_config().get("label_map", {})


def resolve_lane_id(lane: str) -> str | None:
    """Resolve a lane role name to a Trello list ID."""
    return get_lane_map().get(lane)


def resolve_lane_role(list_id: str) -> str | None:
    """Resolve a Trello list ID back to a lane role name."""
    lane_map = get_lane_map()
    for role, lid in lane_map.items():
        if lid == list_id:
            return role
    return None


def resolve_label_ids(labels: list[str]) -> list[str]:
    """Resolve label names to Trello label IDs, skipping unknowns."""
    label_map = get_label_map()
    return [label_map[name] for name in labels if name in label_map]


async def trello_request(method: str, path: str, **kwargs) -> dict | list:
    """
    Make an authenticated Trello API request.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API path (e.g. "/boards/{id}/lists")
        **kwargs: Extra args passed to httpx (json, params, files, etc.)

    Returns:
        Parsed JSON response.

    Raises:
        ImportError: If httpx is not installed.
        Exception: On HTTP or connection errors (with descriptive message).
    """
    import httpx

    auth = get_auth_params()
    if not auth:
        raise Exception("Trello not configured. Use configure_trello to set your API key and token.")

    # Merge auth params into query params
    params = kwargs.pop("params", {})
    params.update(auth)

    url = f"{API_BASE}{path}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(method, url, params=params, **kwargs)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()


async def trello_upload(path: str, file_path: str, filename: str, **kwargs) -> dict:
    """
    Upload a file to Trello API.

    Args:
        path: API path (e.g. "/cards/{id}/attachments")
        file_path: Local path to the file to upload.
        filename: Name for the uploaded file.
        **kwargs: Extra params.

    Returns:
        Parsed JSON response.
    """
    import httpx

    auth = get_auth_params()
    if not auth:
        raise Exception("Trello not configured. Use configure_trello to set your API key and token.")

    params = kwargs.pop("params", {})
    params.update(auth)

    url = f"{API_BASE}{path}"

    with open(file_path, "rb") as f:
        files = {"file": (filename, f, "application/octet-stream")}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, params=params, files=files)
            resp.raise_for_status()
            return resp.json()
