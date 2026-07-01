"""
Game state tools - Query structured game state and run test scenarios.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from mcp.types import Tool, TextContent

from utils import find_main_lua


# Tool definitions
GET_GAME_STATE_TOOL = Tool(
    name="get_game_state",
    description=(
        "Get structured game state as JSON. Returns current scene, combat state "
        "(phase, health, shield, hand cards with positions, effects, enemy info), "
        "player stats, and UI state. Much faster and more reliable than parsing screenshots. "
        "Combat phase is one of: player_turn, stat_choice, animating, combat_end."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            }
        },
        "required": ["project_path"]
    }
)

RUN_SCENARIO_TOOL = Tool(
    name="run_scenario",
    description=(
        "Configure and launch a test scenario without restarting the simulator. "
        "Can load a saved scenario file from scenarios/ OR pass settings inline. "
        "If 'filename' is provided, loads that file and any other params override its values. "
        "Can start combat, open a story/event, navigate to the map, or go to any scene. "
        "Optionally seeds math.random for deterministic replay. "
        "\n\n"
        "**Scripted scenarios:** If the loaded file has a 'steps' array (and optionally a 'setup' "
        "key for the config), the runner executes each step and returns a structured pass/fail report. "
        "Step actions: wait_for, verify, wait, tap, drag, play_card, tap_stat, tap_choice. "
        "Verify operators: direct value (==), or {\"<\":N}, {\">=\":N}, {\"!=\":N}, {\"exists\":bool}, {\"contains\":val}. "
        "State paths use dot notation: 'combat.player.health', 'combat.hand.cards.0.name'."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            },
            "filename": {
                "type": "string",
                "description": "Load scenario from scenarios/ folder (e.g. 'basic_bandit.json'). "
                               "Other params override values from the file."
            },
            "scene": {
                "type": "string",
                "description": "Scene to launch: 'Combat', 'Journal', 'Menu', 'Load', 'TrophyV2', 'HighScoreV2', etc. "
                               "If omitted, inferred from other fields (enemy_deck -> Combat, story -> Journal)."
            },
            "story": {
                "type": "string",
                "description": "Story to open in Journal scene (e.g. 'Argoria Map', 'Player Inventory')"
            },
            "enemy_deck": {
                "type": "string",
                "description": "Enemy deck: Bandit, goblin, spider, Werewolf, Sorceress, basilisk, "
                               "Merlock, MerlockHard, necromancer, thief, trainerFire, trainerIce, "
                               "brotherhood, ratmen, wisp, scouts, kidnappers, Hubert, HubertHard, "
                               "MechaSpider, MadTrainer, random"
            },
            "weapon": {
                "type": "string",
                "description": "Player weapon: Spear, BladeStaff, EnchantedStaff, Axe, BattleAxe, "
                               "EnchantedAxe, ShortSword, LongSword, EnchantedSword, ShortBow, LongBow, EnchantedBow"
            },
            "magic": {
                "type": "string",
                "description": "Magic type: fire, water, nature, storm"
            },
            "combat_speed": {
                "type": "string",
                "description": "Animation speed: slow, normal, fast, very_fast, instant",
                "default": "very_fast"
            },
            "random_seed": {
                "type": "number",
                "description": "Seed for deterministic replay. Same seed = same dice, shuffles, draws."
            },
            "dev_test_pass": {
                "type": "boolean",
                "description": "Force all dice rolls to pass"
            },
            "dev_test_fail": {
                "type": "boolean",
                "description": "Force all dice rolls to fail"
            },
            "dev_max_stats": {
                "type": "boolean",
                "description": "Start with maximum stats"
            },
            "short_combat": {
                "type": "boolean",
                "description": "Shortened combat encounters"
            },
            "conditions": {
                "type": "number",
                "description": "Number of starting conditions (0-4)"
            },
            "companion": {
                "type": "boolean",
                "description": "Enable companion cards"
            },
            "full_dark": {
                "type": "boolean",
                "description": "Enable full darkness effect"
            },
            "effects": {
                "type": "object",
                "description": "Effects at combat start: {\"strength\": 2, \"feebled\": 1}"
            },
            "resists": {
                "type": "object",
                "description": "Player resists: {\"heat\": \"high\", \"cold\": \"low\"}"
            },
            "weakness": {
                "type": "object",
                "description": "Player weaknesses: {\"heat\": \"high\"}"
            },
            "enemy_resists": {
                "type": "object",
                "description": "Enemy resists: {\"cut\": \"high\"}"
            },
            "player": {
                "type": "object",
                "description": "Direct player overrides: {\"str\": 5, \"gold\": 999, \"has_map\": true, "
                               "\"tags\": {\"race\": \"elf\"}}"
            },
            "debug_shops": {
                "type": "boolean",
                "description": "Debug shop system"
            },
            "debug_tutorial": {
                "type": "boolean",
                "description": "Debug tutorial overlays"
            },
            "time_advance": {
                "type": "number",
                "description": "Auto-advance time (0=disabled, 1-5)"
            },
            "event_count": {
                "type": "number",
                "description": "Number of events before endgame (default 5)"
            },
            "fast_time_combat_win": {
                "type": "boolean",
                "description": "Skip combat win animation"
            },
            "fast_time_combat_lose": {
                "type": "boolean",
                "description": "Skip combat lose animation"
            }
        },
        "required": ["project_path"]
    }
)

LIST_SCENARIOS_TOOL = Tool(
    name="list_scenarios",
    description=(
        "List saved test scenario files from the project's scenarios/ folder. "
        "Shows name, description, and key settings for each."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to the project directory or main.lua file"
            }
        },
        "required": ["project_path"]
    }
)

# Export all tools
TOOLS = [GET_GAME_STATE_TOOL, RUN_SCENARIO_TOOL, LIST_SCENARIOS_TOOL]

# Export handlers map
HANDLERS = {
    "get_game_state": None,
    "run_scenario": None,
    "list_scenarios": None,
}


def _get_project_name(project_path: str) -> str:
    """Get the project name from the path."""
    main_lua_path = find_main_lua(project_path)
    project_dir = str(Path(main_lua_path).parent)
    return Path(project_dir).name


def _get_state_output_file(project_name: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"solar2d_state_{project_name}.json")


def _get_scenario_control_file(project_name: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"solar2d_scenario_{project_name}.json")


def _get_scenarios_dir(project_path: str) -> str:
    """Get the scenarios directory for the project."""
    main_lua_path = find_main_lua(project_path)
    project_dir = str(Path(main_lua_path).parent)
    return os.path.join(project_dir, "scenarios")


def _read_state(project_name: str) -> dict | None:
    """Read the current game state file. The game writes this continuously."""
    output_file = _get_state_output_file(project_name)

    if not os.path.exists(output_file):
        return None

    try:
        with open(output_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


async def handle_get_game_state(arguments: dict) -> list[TextContent]:
    """Handle get_game_state tool call."""
    project_path = arguments.get("project_path")

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    project_name = _get_project_name(project_path)
    state = _read_state(project_name)

    if state is None:
        return [TextContent(
            type="text",
            text="No game state file found. Make sure the simulator is running."
        )]

    if "error" in state:
        return [TextContent(type="text", text=f"Error from game: {state['error']}")]

    return [TextContent(
        type="text",
        text=json.dumps(state, indent=2)
    )]


async def handle_run_scenario(arguments: dict) -> list[TextContent]:
    """Handle run_scenario tool call. Loads file + inline overrides, or just inline.

    If the scenario contains a 'steps' array, executes it as a scripted test
    and returns a structured pass/fail report.
    """
    project_path = arguments.get("project_path")

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    # Start with file contents if filename provided
    scenario = {}
    filename = arguments.get("filename")
    if filename:
        scenarios_dir = _get_scenarios_dir(project_path)
        filepath = os.path.join(scenarios_dir, filename)

        if not os.path.exists(filepath):
            return [TextContent(type="text", text=f"Scenario file not found: {filepath}")]

        try:
            with open(filepath, 'r') as f:
                scenario = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            return [TextContent(type="text", text=f"Error reading scenario: {e}")]

        # Remove metadata the game doesn't need
        scenario.pop("name", None)
        scenario.pop("description", None)

    # Detect scripted scenario (has 'steps' array)
    steps = scenario.pop("steps", None)

    # Setup config: either the 'setup' key or the whole scenario (legacy format)
    setup = scenario.pop("setup", scenario)

    # Override/merge with inline params (inline wins over file)
    for key, value in arguments.items():
        if key not in ("project_path", "filename") and value is not None:
            setup[key] = value

    # Default combat speed to very_fast for testing
    if "combat_speed" not in setup:
        setup["combat_speed"] = "very_fast"

    project_name = _get_project_name(project_path)
    control_file = _get_scenario_control_file(project_name)

    # If scenario has a random_seed, we need to restart the simulator
    # so the seed is applied at startup (Phase 1 in _mcp_state.lua)
    if setup.get("random_seed") is not None:
        from utils import running_projects
        from tools import run_project
        import subprocess
        import signal

        main_lua_path = find_main_lua(project_path)
        project_dir = str(Path(main_lua_path).parent)

        # Kill any existing tracked simulator
        if project_dir in running_projects:
            old = running_projects[project_dir]
            try:
                os.kill(old["pid"], signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
            del running_projects[project_dir]

        # Also kill any externally-running Corona Simulator processes
        # (in case the MCP server was restarted while the sim was running)
        try:
            subprocess.run(
                ["pkill", "-f", "Corona Simulator"],
                capture_output=True,
                timeout=5
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        await asyncio.sleep(0.8)  # Give the kill time to take effect

        # Write scenario file BEFORE launching simulator
        with open(control_file, 'w') as f:
            json.dump(setup, f)

        # Relaunch simulator (it will pick up the scenario at startup)
        await run_project.handle({"project_path": project_path, "debug": True})
        await asyncio.sleep(2)  # Give simulator time to boot
    else:
        # No seed -- write to running simulator
        with open(control_file, 'w') as f:
            json.dump(setup, f)

    # Determine expected scene
    expected_scene = setup.get("scene")
    if not expected_scene:
        if setup.get("enemy_deck") or setup.get("debug_combat"):
            expected_scene = "Combat"
        elif any(setup.get(k) for k in ["story", "debug_story", "debug_event", "debug_shops", "debug_map"]):
            expected_scene = "Journal"

    # Wait for setup scene transition (up to 10 seconds for restart scenarios)
    timeout = 100 if setup.get("random_seed") is not None else 50
    setup_state = None
    for _ in range(timeout):
        await asyncio.sleep(0.1)
        s = _read_state(project_name)
        if s:
            current_scene = s.get("scene")
            if expected_scene is None or current_scene == expected_scene:
                setup_state = s
                break

    label = f"'{filename}'" if filename else "inline scenario"

    if setup_state is None:
        return [TextContent(
            type="text",
            text=f"Scenario {label} setup failed: scene did not transition within 5 seconds."
        )]

    # If no scripted steps, return the setup state (legacy behavior)
    if not steps:
        return [TextContent(
            type="text",
            text=f"Scenario {label} loaded! Scene: {setup_state.get('scene')}\n\n{json.dumps(setup_state, indent=2)}"
        )]

    # Execute scripted steps
    report = await _run_scripted_steps(steps, project_name, project_path)
    report["scenario"] = filename or "inline"

    return [TextContent(
        type="text",
        text=json.dumps(report, indent=2)
    )]


# ===== Scripted scenario runner =====

def _get_path(obj, path):
    """Walk a dot-path into a nested dict/list structure. Returns None if not found."""
    if obj is None:
        return None
    parts = path.split(".")
    current = obj
    for part in parts:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _eval_comparison(actual, expected):
    """Evaluate whether actual matches expected.

    expected can be:
        - a direct value (equality check)
        - a dict like {"<": 5}, {">=": 0}, {"!=": null}, {"exists": true}
    """
    if isinstance(expected, dict):
        for op, val in expected.items():
            if op == "==":
                if actual != val:
                    return False
            elif op == "!=":
                if actual == val:
                    return False
            elif op == "<":
                if actual is None or not (actual < val):
                    return False
            elif op == "<=":
                if actual is None or not (actual <= val):
                    return False
            elif op == ">":
                if actual is None or not (actual > val):
                    return False
            elif op == ">=":
                if actual is None or not (actual >= val):
                    return False
            elif op == "exists":
                if (actual is not None) != val:
                    return False
            elif op == "contains":
                if actual is None or val not in actual:
                    return False
            else:
                return False
        return True
    return actual == expected


def _state_matches(state, condition):
    """Check if a state object matches all key/value pairs in condition.

    condition keys are dot-paths into the state.
    """
    for path, expected in condition.items():
        actual = _get_path(state, path)
        if not _eval_comparison(actual, expected):
            return False
    return True


async def _action_wait_for(args, project_name):
    """Poll state until condition matches or timeout."""
    timeout = args.pop("timeout", 10)
    elapsed = 0.0
    poll_interval = 0.2
    last_state = None
    while elapsed < timeout:
        last_state = _read_state(project_name)
        if last_state and _state_matches(last_state, args):
            return {"ok": True}
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    return {
        "ok": False,
        "reason": f"timeout after {timeout}s waiting for condition",
        "condition": args,
        "last_state": last_state,
    }


async def _action_verify(args, project_name):
    """Assert state values match expected. Fails on first mismatch."""
    state = _read_state(project_name)
    if state is None:
        return {"ok": False, "reason": "no game state available"}

    failures = []
    for path, expected in args.items():
        actual = _get_path(state, path)
        if not _eval_comparison(actual, expected):
            failures.append({
                "path": path,
                "expected": expected,
                "actual": actual,
            })

    if failures:
        return {"ok": False, "reason": "verification failed", "failures": failures}
    return {"ok": True}


async def _action_wait(args, project_name):
    """Sleep for N milliseconds."""
    ms = args.get("ms", args.get("duration", 500))
    await asyncio.sleep(ms / 1000.0)
    return {"ok": True}


async def _action_tap(args, project_name, project_path):
    """Raw simulate_tap pass-through."""
    from tools import touch
    args = dict(args)
    args["project_path"] = project_path
    result = await touch.handle_simulate_tap(args)
    return {"ok": True, "tap_result": result[0].text if result else ""}


async def _action_drag(args, project_name, project_path):
    """Raw simulate_drag pass-through."""
    from tools import touch
    args = dict(args)
    args["project_path"] = project_path
    result = await touch.handle_simulate_drag(args)
    return {"ok": True, "drag_result": result[0].text if result else ""}


async def _action_play_card(args, project_name, project_path):
    """Drag a card from hand to a play zone.

    args:
      index: 1-based card index in hand
      side: "left" or "right"
    """
    from tools import touch
    state = _read_state(project_name)
    cards = _get_path(state, "combat.hand.cards") or []
    index = args.get("index", 1)
    side = args.get("side", "left")

    if index < 1 or index > len(cards):
        return {
            "ok": False,
            "reason": f"card index {index} out of range (hand has {len(cards)} cards)",
        }

    card = cards[index - 1]
    bounds = card.get("bounds")

    if bounds and "center_x_pct" in bounds:
        # Use the card's anchor center point
        cx = bounds["center_x_pct"]
        cy = bounds["center_y_pct"]
        start_left, start_right = cx, cx
        start_top, start_bottom = cy, cy
    elif bounds:
        cx = (bounds["left_pct"] + bounds["right_pct"]) / 2
        cy = (bounds["top_pct"] + bounds["bottom_pct"]) / 2
        start_left, start_right = cx, cx
        start_top, start_bottom = cy, cy
    else:
        # Fallback center point
        start_left, start_right = 17, 17
        start_top, start_bottom = 88, 88

    # Play zone target center
    if side == "left":
        end_x = 20
    else:
        end_x = 80
    end_y = 30

    drag_args = {
        "project_path": project_path,
        "start_left": start_left,
        "start_right": start_right,
        "start_top": start_top,
        "start_bottom": start_bottom,
        "end_left": end_x,
        "end_right": end_x,
        "end_top": end_y,
        "end_bottom": end_y,
        "duration": 500,
    }
    await touch.handle_simulate_drag(drag_args)
    return {"ok": True, "card": card.get("name"), "side": side, "bounds": bounds}


async def _action_tap_stat(args, project_name, project_path):
    """Tap left or right stat button using bounds from state."""
    from tools import touch
    side = args if isinstance(args, str) else args.get("side", "left")

    state = _read_state(project_name)
    positions = _get_path(state, "combat.positions") or {}
    key = "stat_left" if side == "left" else "stat_right"
    bounds = positions.get(key)

    if bounds:
        cx = (bounds["left_pct"] + bounds["right_pct"]) / 2
        cy = (bounds["top_pct"] + bounds["bottom_pct"]) / 2
        tap_args = {"left": cx, "right": cx, "top": cy, "bottom": cy}
    else:
        # Fallback
        if side == "left":
            tap_args = {"left": 10, "right": 10, "top": 48, "bottom": 48}
        else:
            tap_args = {"left": 85, "right": 85, "top": 48, "bottom": 48}

    tap_args["project_path"] = project_path
    await touch.handle_simulate_tap(tap_args)
    return {"ok": True, "side": side, "bounds": bounds}


async def _action_tap_choice(args, project_name, project_path):
    """Tap a story or tarot choice by index (1-based).

    args:
      index: 1-based choice number
      type: "tarot" or "story" (default: "story")
    """
    from tools import touch
    index = args.get("index", 1) if isinstance(args, dict) else args
    choice_type = args.get("type", "story") if isinstance(args, dict) else "story"

    tap_args = None

    if choice_type == "tarot":
        # Use bounds from state
        state = _read_state(project_name)
        positions = _get_path(state, "combat.positions") or {}
        key = f"tarot_choice_{index}"
        bounds = positions.get(key)
        if bounds:
            cx = (bounds["left_pct"] + bounds["right_pct"]) / 2
            cy = (bounds["top_pct"] + bounds["bottom_pct"]) / 2
            tap_args = {"left": cx, "right": cx, "top": cy, "bottom": cy}

    if tap_args is None:
        # Fallback to hardcoded positions
        if choice_type == "tarot":
            if index == 1:
                tap_args = {"left": 10, "right": 80, "top": 65, "bottom": 73}
            else:
                tap_args = {"left": 10, "right": 80, "top": 76, "bottom": 84}
        else:
            y_starts = [62, 71, 80]
            y = y_starts[min(index - 1, 2)]
            tap_args = {"left": 20, "right": 70, "top": y, "bottom": y + 4}

    tap_args["project_path"] = project_path
    await touch.handle_simulate_tap(tap_args)
    return {"ok": True, "index": index, "type": choice_type}


def _get_command_control_file(project_name: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"solar2d_command_{project_name}.json")


async def _send_command(project_name: str, cmd: dict):
    """Write a command to the command control file for the Lua side to pick up."""
    control_file = _get_command_control_file(project_name)
    with open(control_file, 'w') as f:
        json.dump(cmd, f)
    # Give the Lua poller time to read it (polls at 100ms)
    await asyncio.sleep(0.2)


async def _action_set_next_enemy_card(args, project_name):
    """Force the next enemy card draw to be a specific card (by name)."""
    name = args if isinstance(args, str) else args.get("name") or args.get("value")
    if not name:
        return {"ok": False, "reason": "set_next_enemy_card requires a card name string"}
    await _send_command(project_name, {"cmd": "set_next_enemy_card", "value": name})
    return {"ok": True, "card": name}


async def _action_set_next_player_cards(args, project_name):
    """Force the next N player card draws to be specific cards (by name, in order)."""
    if isinstance(args, list):
        names = args
    elif isinstance(args, dict):
        names = args.get("cards") or args.get("value") or []
    else:
        return {"ok": False, "reason": "set_next_player_cards requires a list of card names"}
    if not isinstance(names, list):
        return {"ok": False, "reason": "set_next_player_cards value must be a list"}
    await _send_command(project_name, {"cmd": "set_next_player_cards", "value": names})
    return {"ok": True, "cards": names}


async def _action_set_next_dice_roll(args, project_name):
    """Force the next dice roll to return a specific value."""
    if isinstance(args, (int, float)):
        value = int(args)
    elif isinstance(args, dict):
        value = args.get("value")
    else:
        return {"ok": False, "reason": "set_next_dice_roll requires a number"}
    if value is None:
        return {"ok": False, "reason": "set_next_dice_roll requires a number"}
    await _send_command(project_name, {"cmd": "set_next_dice_roll", "value": value})
    return {"ok": True, "value": value}


# Action dispatch table: action name -> (handler, needs_project_path)
_ACTIONS = {
    "wait_for": (_action_wait_for, False),
    "verify": (_action_verify, False),
    "wait": (_action_wait, False),
    "tap": (_action_tap, True),
    "drag": (_action_drag, True),
    "play_card": (_action_play_card, True),
    "tap_stat": (_action_tap_stat, True),
    "tap_choice": (_action_tap_choice, True),
    "set_next_enemy_card": (_action_set_next_enemy_card, False),
    "set_next_player_cards": (_action_set_next_player_cards, False),
    "set_next_dice_roll": (_action_set_next_dice_roll, False),
}


async def _run_scripted_steps(steps, project_name, project_path):
    """Execute a list of scenario steps in sequence. Returns a report dict."""
    report = {
        "ok": True,
        "steps_total": len(steps),
        "steps_passed": 0,
        "steps_results": [],
    }

    for i, step in enumerate(steps):
        if not isinstance(step, dict) or len(step) != 1:
            report["ok"] = False
            report["failed_step"] = {
                "index": i,
                "reason": "step must be a dict with exactly one key (the action name)",
                "step": step,
            }
            return report

        action_name, args = next(iter(step.items()))
        handler_entry = _ACTIONS.get(action_name)

        if handler_entry is None:
            report["ok"] = False
            report["failed_step"] = {
                "index": i,
                "action": action_name,
                "reason": f"unknown action '{action_name}'",
                "available_actions": sorted(_ACTIONS.keys()),
            }
            return report

        handler, needs_project_path = handler_entry
        try:
            if needs_project_path:
                result = await handler(args, project_name, project_path)
            else:
                result = await handler(args, project_name)
        except Exception as e:
            report["ok"] = False
            report["failed_step"] = {
                "index": i,
                "action": action_name,
                "args": args,
                "reason": f"action raised exception: {type(e).__name__}: {e}",
            }
            return report

        result_summary = {"index": i, "action": action_name, "ok": result.get("ok", False)}
        report["steps_results"].append(result_summary)

        if not result.get("ok"):
            report["ok"] = False
            report["failed_step"] = {
                "index": i,
                "action": action_name,
                "args": args,
                **{k: v for k, v in result.items() if k != "ok"},
            }
            # Capture state at failure for debugging
            report["state_at_failure"] = _read_state(project_name)
            return report

        report["steps_passed"] += 1

    return report


async def handle_list_scenarios(arguments: dict) -> list[TextContent]:
    """Handle list_scenarios tool call. Walks subdirectories recursively and groups by folder."""
    project_path = arguments.get("project_path")

    if not project_path:
        return [TextContent(type="text", text="Error: project_path is required")]

    scenarios_dir = _get_scenarios_dir(project_path)

    if not os.path.exists(scenarios_dir):
        return [TextContent(type="text", text=f"No scenarios/ folder found at {scenarios_dir}")]

    # Walk recursively, group by relative folder path
    scenarios_by_folder = {}  # {folder_path: [filenames]}
    total_count = 0
    for root, dirs, files in os.walk(scenarios_dir):
        json_files = sorted(f for f in files if f.endswith(".json"))
        if not json_files:
            continue
        rel_dir = os.path.relpath(root, scenarios_dir)
        if rel_dir == ".":
            rel_dir = ""  # root level
        scenarios_by_folder[rel_dir] = json_files
        total_count += len(json_files)

    if total_count == 0:
        return [TextContent(type="text", text="No scenario files found in scenarios/")]

    lines = [f"Found {total_count} scenario(s) in {len(scenarios_by_folder)} folder(s):\n"]

    # Sort folders: root first, then alphabetical
    folder_order = sorted(scenarios_by_folder.keys(), key=lambda f: (f != "", f))

    for folder in folder_order:
        files = scenarios_by_folder[folder]
        folder_label = folder if folder else "(root)"
        lines.append(f"📁 {folder_label}/")
        for filename in files:
            rel_path = os.path.join(folder, filename) if folder else filename
            filepath = os.path.join(scenarios_dir, rel_path)
            try:
                with open(filepath, 'r') as f:
                    scenario = json.load(f)
                name = scenario.get("name", filename)
                desc = scenario.get("description", "")
                # Setup may be top-level (legacy) or nested in "setup"
                setup = scenario.get("setup", scenario)
                enemy = setup.get("enemy_deck", "?")
                weapon = setup.get("weapon", "?")
                seed = setup.get("random_seed", "none")
                scripted = "✓" if scenario.get("steps") else " "
                lines.append(f"  [{scripted}] {filename}")
                lines.append(f"      {name}")
                if desc:
                    lines.append(f"      {desc}")
                lines.append(f"      enemy={enemy}  weapon={weapon}  seed={seed}")
            except (json.JSONDecodeError, IOError) as e:
                lines.append(f"  [!] {filename} (error reading: {e})")
        lines.append("")

    lines.append("Run with: run_scenario(filename=\"folder/file.json\")")
    lines.append("Legend: [✓] = scripted (has steps), [ ] = setup-only")

    return [TextContent(type="text", text="\n".join(lines))]


# Wire up handlers
HANDLERS["get_game_state"] = handle_get_game_state
HANDLERS["run_scenario"] = handle_run_scenario
HANDLERS["list_scenarios"] = handle_list_scenarios
