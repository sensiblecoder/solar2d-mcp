"""
SolarScope tools - drive the SolarScope in-game test framework.

These are thin conveniences over the SolarScope runtime:
- run_solar_scope_test:   launch the sim running a specific test module.
- rerun_solar_scope_test: hot-reload a test into an ALREADY-running sim (no relaunch)
                          via SolarScope's command channel.
- get_solar_scope_result: read the structured result the run writes to the sandbox.

SolarScope keeps the logic in Lua; these tools only cross the process boundary
(pick a test, read the result file).
"""

import json
import time
from pathlib import Path

from mcp.types import TextContent, Tool

from utils import find_main_lua

# ---- command channel (project dir) ---------------------------------------

_last_seq = 0


def _next_seq() -> int:
    """Monotonic sequence, millisecond-based but strictly increasing."""
    global _last_seq
    s = int(time.time() * 1000)
    if s <= _last_seq:
        s = _last_seq + 1
    _last_seq = s
    return s


def _project_dir(project_path: str) -> str:
    return str(Path(find_main_lua(project_path)).parent)


def _write_command(project_dir: str, action: str, module: str | None) -> int:
    """Write <project>/.solar_scope/command.json for the app poller to pick up."""
    seq = _next_seq()
    d = Path(project_dir) / ".solar_scope"
    d.mkdir(parents=True, exist_ok=True)
    payload = {"seq": seq, "action": action}
    if module is not None:
        payload["module"] = module
    (d / "command.json").write_text(json.dumps(payload))
    return seq


# ---- result file (sandbox) -----------------------------------------------

def _result_candidates(project_dir: str) -> list[Path]:
    """Newest-first result.latest.json across this project's Corona sandboxes."""
    base = Path(project_dir).name
    support = Path.home() / "Library" / "Application Support" / "Corona Simulator"
    matches = list(support.glob(f"{base}-*/Documents/solar_scope/result.latest.json"))
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches


def _read_result(project_dir: str) -> dict | None:
    for path in _result_candidates(project_dir):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            continue
    return None


# ---- tools ---------------------------------------------------------------

RUN_TOOL = Tool(
    name="run_solar_scope_test",
    description=(
        "Launch a Solar2D project in the simulator running a specific SolarScope test "
        "module (e.g. 'tests.regression.record_replay'), without editing the game's "
        "config. Replaces any running instance. Returns the command sequence to pass to "
        "get_solar_scope_result."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {"type": "string", "description": "Project directory or main.lua path"},
            "test_module": {"type": "string", "description": "Test module to autorun, e.g. 'tests.regression.match_clears'"},
        },
        "required": ["project_path", "test_module"],
    },
)

RERUN_TOOL = Tool(
    name="rerun_solar_scope_test",
    description=(
        "Hot-reload a SolarScope test into an ALREADY-running simulator via the command "
        "channel, without relaunching. Much faster than run_solar_scope_test for iterating. "
        "The sim must already be running (use run_solar_scope_test first). Returns the "
        "command sequence to pass to get_solar_scope_result."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {"type": "string", "description": "Project directory or main.lua path"},
            "test_module": {"type": "string", "description": "Test module to run, e.g. 'tests.regression.invalid_swap'"},
        },
        "required": ["project_path", "test_module"],
    },
)

RESULT_TOOL = Tool(
    name="get_solar_scope_result",
    description=(
        "Read the structured result of the most recent SolarScope run (status, message, "
        "errors, artifacts, probe report) from the project's sandbox. Optionally wait for "
        "the result of a specific command sequence."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {"type": "string", "description": "Project directory or main.lua path"},
            "wait_seq": {"type": "number", "description": "If set, poll until a result with seq >= this value appears (or timeout)."},
            "timeout_ms": {"type": "number", "description": "Max time to wait for wait_seq (default 8000).", "default": 8000},
        },
        "required": ["project_path"],
    },
)

TOOLS = [RUN_TOOL, RERUN_TOOL, RESULT_TOOL]


async def handle_run(arguments: dict) -> list[TextContent]:
    project_path = arguments.get("project_path")
    test_module = arguments.get("test_module")
    if not project_path or not test_module:
        return [TextContent(type="text", text="Error: project_path and test_module are required")]

    project_dir = _project_dir(project_path)
    seq = _write_command(project_dir, "run", test_module)

    # Launch (or relaunch) the sim; its boot poll picks up the command we just wrote.
    from tools import run_project  # lazy import avoids import-time cycles

    launch = await run_project.handle({"project_path": project_path})
    launch_text = launch[0].text if launch else ""
    return [TextContent(
        type="text",
        text=(
            f"Launched SolarScope test '{test_module}' (seq {seq}).\n"
            f"Call get_solar_scope_result(project_path, wait_seq={seq}) for the result.\n\n"
            f"{launch_text}"
        ),
    )]


async def handle_rerun(arguments: dict) -> list[TextContent]:
    project_path = arguments.get("project_path")
    test_module = arguments.get("test_module")
    if not project_path or not test_module:
        return [TextContent(type="text", text="Error: project_path and test_module are required")]

    project_dir = _project_dir(project_path)
    seq = _write_command(project_dir, "run", test_module)
    return [TextContent(
        type="text",
        text=(
            f"Queued hot-reload of '{test_module}' (seq {seq}) into the running simulator.\n"
            f"Call get_solar_scope_result(project_path, wait_seq={seq}) for the result.\n"
            f"(If nothing updates, the sim may not be running — use run_solar_scope_test.)"
        ),
    )]


async def handle_get_result(arguments: dict) -> list[TextContent]:
    project_path = arguments.get("project_path")
    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    project_dir = _project_dir(project_path)
    wait_seq = arguments.get("wait_seq")
    timeout_ms = arguments.get("timeout_ms", 8000)

    result = _read_result(project_dir)
    if wait_seq is not None:
        import asyncio

        deadline = time.time() + (timeout_ms / 1000.0)
        while True:
            result = _read_result(project_dir)
            if result is not None and (result.get("seq") or 0) >= wait_seq:
                break
            if time.time() >= deadline:
                if result is None:
                    return [TextContent(type="text", text="No SolarScope result found yet (timed out waiting).")]
                return [TextContent(
                    type="text",
                    text=(
                        f"Timed out waiting for seq {wait_seq}; latest result is seq "
                        f"{result.get('seq')}:\n\n{json.dumps(result, indent=2)}"
                    ),
                )]
            await asyncio.sleep(0.15)

    if result is None:
        return [TextContent(type="text", text="No SolarScope result found. Has the project run a test yet?")]

    status = result.get("status", "?")
    name = result.get("name", "?")
    header = f"SolarScope result: {status.upper()} — {name} (seq {result.get('seq')})"
    return [TextContent(type="text", text=f"{header}\n\n{json.dumps(result, indent=2)}")]
