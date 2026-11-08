"""
Video tools - record the simulator window at 60fps with its audio, and export social-ready cuts.

Recording runs capture/simcap (a ScreenCaptureKit window recorder, compiled from
capture/simcap.swift on first use) as a detached process. It records the Corona
Simulator's window at native Retina pixels, cropped to the game's content aspect
(the title bar is dropped), with the simulator's own audio only. The game does no
work for it: nothing is saved from inside Lua, so the frame rate you see is the
frame rate you get.

State lives in a JSON file in the temp dir, not in this process, because several
MCP server processes (one per client session) may share one simulator.
"""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from mcp.types import TextContent, Tool

from utils import find_main_lua

ROOT = Path(__file__).resolve().parent.parent
SIMCAP_SRC = ROOT / "capture" / "simcap.swift"
SIMCAP_BIN = ROOT / "capture" / ".build" / "simcap"

# Masters are kept (they are marketing footage), so they live under ~/Movies, not the temp dir.
VIDEO_ROOT = Path.home() / "Movies" / "solar2d-mcp"

DEFAULT_SECONDS = 60
MAX_SECONDS = 600
START_TIMEOUT = 8.0   # seconds to wait for the first frame before calling the start a failure
STOP_TIMEOUT = 30.0   # finishing a long HEVC file takes a moment

# Export presets. scale = output box (WxH); the source is scaled to fill and center-cropped.
PRESETS = {
    "x": {
        "desc": "X/Twitter: 1920x1080 60fps H.264, audio loudness-normalized (X caps video at 2:20)",
        "scale": (1920, 1080), "fps": 60, "crf": 16, "loudnorm": True, "max_seconds": 140,
    },
    "youtube": {
        "desc": "YouTube/Steam: 2560x1440 60fps H.264, high bitrate",
        "scale": (2560, 1440), "fps": 60, "crf": 14, "loudnorm": True,
    },
    "vertical": {
        "desc": "Shorts/TikTok/Reels: 1080x1920 60fps, a 9:16 slice of the field (aim it with focus_x)",
        "scale": (1080, 1920), "fps": 60, "crf": 17, "loudnorm": True, "max_seconds": 180,
    },
    "preview": {
        "desc": "Small 960px 30fps MP4 for a quick look (SendUserFile)",
        "scale": (960, 540), "fps": 30, "crf": 26, "loudnorm": False,
    },
    "master": {
        "desc": "ProRes 422 HQ .mov at the native capture size, for the editor",
        "prores": True,
    },
}


START_TOOL = Tool(
    name="start_video_recording",
    description=(
        "Start recording the Solar2D simulator window as video: native Retina resolution, 60fps, with the "
        "simulator's own audio, title bar cropped off. Runs in the background and returns once the first frame "
        "is captured. Workflow: start_video_recording -> drive the sim (run_solar_scope_test harness / simulate_tap) "
        "-> stop_video_recording -> export_video (preset 'x', 'youtube', 'vertical', 'preview' or 'master'). "
        "Masters are kept under ~/Movies/solar2d-mcp/<project>/. Note simulate_tap/find_object draw a marker into the "
        "game frame, so drive marketing takes with a SolarScope harness instead."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {"type": "string", "description": "Path to the project directory or main.lua file"},
            "name": {"type": "string", "description": "Recording name (file stem). Default: timestamp."},
            "duration": {
                "type": "number",
                "description": f"Stop by itself after this many seconds (default {DEFAULT_SECONDS}, max {MAX_SECONDS}). "
                               "stop_video_recording can end it earlier.",
                "default": DEFAULT_SECONDS,
            },
            "fps": {"type": "number", "description": "Capture frame rate (default 60).", "default": 60},
            "codec": {
                "type": "string", "enum": ["hevc", "prores"],
                "description": "Master codec: hevc (default, ~60Mbps, compact) or prores (ProRes 422 HQ, huge, edit-grade).",
                "default": "hevc",
            },
            "audio": {"type": "boolean", "description": "Capture the simulator's audio (default true).", "default": True},
            "crop": {
                "type": "boolean",
                "description": "Crop to the game's content aspect (drops the window title bar). Default true.",
                "default": True,
            },
        },
        "required": ["project_path"],
    },
)

STOP_TOOL = Tool(
    name="stop_video_recording",
    description="Stop the running simulator video recording, wait for the file to finish, and report its path, "
                "frame count and delivered fps. Also reports a recording that already stopped on its own.",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {"type": "string", "description": "Path to the project directory or main.lua file"},
        },
        "required": ["project_path"],
    },
)

EXPORT_TOOL = Tool(
    name="export_video",
    description=(
        "Export a recording to a delivery format. Presets: "
        + "; ".join(f"'{k}' = {v['desc']}" for k, v in PRESETS.items())
        + ". Output is constant frame rate with faststart, so it plays inline in the Claude app (SendUserFile, "
          "display: render) and uploads cleanly. Trim with start/end (seconds into the recording)."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {"type": "string", "description": "Path to the project directory or main.lua file"},
            "recording": {
                "type": "string",
                "description": "Recording name (as listed by list_video_recordings) or a path to any video file. "
                               "Default: the most recent recording.",
            },
            "preset": {"type": "string", "enum": list(PRESETS), "default": "x"},
            "start": {"type": "number", "description": "Trim: start time in seconds (default 0)."},
            "end": {"type": "number", "description": "Trim: end time in seconds (default: end of recording)."},
            "focus_x": {
                "type": "number",
                "description": "For crops narrower than the source (vertical): horizontal center of the slice, "
                               "0-100% of the frame width (default 50).",
            },
            "filename": {"type": "string", "description": "Output file name. Default: <recording>-<preset>.mp4"},
        },
        "required": ["project_path"],
    },
)

LIST_TOOL = Tool(
    name="list_video_recordings",
    description="List the project's video recordings and exports (newest first) with duration, size and resolution.",
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {"type": "string", "description": "Path to the project directory or main.lua file"},
        },
        "required": ["project_path"],
    },
)

TOOLS = [START_TOOL, STOP_TOOL, EXPORT_TOOL, LIST_TOOL]


def _text(s: str) -> list[TextContent]:
    return [TextContent(type="text", text=s)]


def _project(project_path: str) -> tuple[str, Path]:
    main_lua = Path(find_main_lua(project_path))
    return main_lua.parent.name, main_lua.parent


def _video_dir(project_name: str) -> Path:
    d = VIDEO_ROOT / project_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_file(project_name: str) -> Path:
    return Path(tempfile.gettempdir()) / f"solar2d_video_{project_name}.json"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _read_state(project_name: str) -> dict | None:
    try:
        return json.loads(_state_file(project_name).read_text())
    except (OSError, ValueError):
        return None


def _find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for d in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        if os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    return None


async def _ensure_simcap() -> str | None:
    """Compile simcap if the binary is missing or older than its source. Returns an error string or None."""
    if SIMCAP_BIN.exists() and SIMCAP_BIN.stat().st_mtime >= SIMCAP_SRC.stat().st_mtime:
        return None
    swiftc = _find_tool("swiftc")
    if not swiftc:
        return "swiftc not found: install the Xcode command line tools (xcode-select --install)."
    SIMCAP_BIN.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        swiftc, "-O", "-o", str(SIMCAP_BIN), str(SIMCAP_SRC),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        return "simcap failed to compile:\n" + err.decode(errors="replace")[-2000:]
    return None


def _content_aspect(project_name: str) -> str | None:
    """The game's content aspect, from the display info the injected touch module writes."""
    info = Path(tempfile.gettempdir()) / f"solar2d_display_{project_name}.json"
    try:
        d = json.loads(info.read_text())
        w, h = d.get("actualContentWidth"), d.get("actualContentHeight")
        if w and h:
            return f"{w}:{h}"
    except (OSError, ValueError):
        pass
    return None


def _parse_done(log_path: str) -> dict | None:
    try:
        for line in reversed(Path(log_path).read_text().splitlines()):
            if line.startswith("done "):
                return json.loads(line[5:])
    except (OSError, ValueError):
        pass
    return None


def _log_tail(log_path: str, n: int = 15) -> str:
    try:
        return "\n".join(Path(log_path).read_text().splitlines()[-n:])
    except OSError:
        return ""


def _describe(stats: dict) -> str:
    return (
        f"Path: {stats['path']}\n"
        f"{stats['width']}x{stats['height']}, {stats['frames']} frames in {stats['seconds']:.1f}s "
        f"({stats['fps']:.1f} fps delivered), {stats['dropped']} dropped by the encoder, "
        f"stopped by {stats['stopped_by']}\n"
        "(ScreenCaptureKit skips unchanged frames, so a still screen lowers the delivered count; "
        "exports are constant frame rate.)"
        + (f"\nStream error: {stats['stream_error']}" if stats.get("stream_error") else "")
    )


async def handle_start(arguments: dict) -> list[TextContent]:
    project_path = arguments.get("project_path")
    if not project_path:
        return _text("Error: project_path is required")
    project_name, _ = _project(project_path)

    state = _read_state(project_name)
    if state and _alive(state["pid"]):
        return _text(f"Already recording: {state['path']} (since {state['started']}). "
                     "Call stop_video_recording first.")

    err = await _ensure_simcap()
    if err:
        return _text(err)

    duration = min(max(float(arguments.get("duration", DEFAULT_SECONDS)), 1), MAX_SECONDS)
    fps = int(arguments.get("fps", 60))
    codec = arguments.get("codec", "hevc")
    name = arguments.get("name") or datetime.now().strftime("rec-%Y%m%d-%H%M%S")
    name = Path(name).stem
    out = _video_dir(project_name) / f"{name}.mov"
    tmp = Path(tempfile.gettempdir())
    stop_file = tmp / f"solar2d_video_{project_name}.stop"
    log_path = tmp / f"solar2d_video_{project_name}.log"
    stop_file.unlink(missing_ok=True)

    cmd = [str(SIMCAP_BIN), str(out), "--fps", str(fps), "--codec", codec,
           "--max-seconds", str(duration), "--stop-file", str(stop_file)]
    if not arguments.get("audio", True):
        cmd.append("--no-audio")
    aspect = _content_aspect(project_name) if arguments.get("crop", True) else None
    if aspect:
        cmd += ["--aspect", aspect]

    with open(log_path, "w") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    # Wait for the "recording" line (first frame flowing) or an early exit.
    deadline = time.monotonic() + START_TIMEOUT
    started_line = None
    while time.monotonic() < deadline:
        await asyncio.sleep(0.1)
        text = log_path.read_text() if log_path.exists() else ""
        started_line = next((ln for ln in text.splitlines() if ln.startswith("recording ")), None)
        if started_line or proc.poll() is not None:
            break
    if not started_line:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
        return _text("Recording did not start.\n" + _log_tail(str(log_path)) +
                     "\n\nIs the simulator running and visible? The host terminal needs Screen Recording "
                     "permission (System Settings > Privacy & Security > Screen & System Audio Recording).")

    _state_file(project_name).write_text(json.dumps({
        "pid": proc.pid, "path": str(out), "name": name, "stop_file": str(stop_file),
        "log": str(log_path), "started": datetime.now().isoformat(timespec="seconds"), "duration": duration,
    }))
    return _text(
        f"Recording started ({started_line[len('recording '):]}).\n"
        f"Stops by itself after {duration:g}s; stop_video_recording ends it sooner.\n"
        f"Crop: {'content aspect ' + aspect if aspect else 'full window (no display info / crop off)'}"
    )


async def handle_stop(arguments: dict) -> list[TextContent]:
    project_path = arguments.get("project_path")
    if not project_path:
        return _text("Error: project_path is required")
    project_name, _ = _project(project_path)

    state = _read_state(project_name)
    if not state:
        return _text("No recording to stop (none started this run).")

    if _alive(state["pid"]):
        Path(state["stop_file"]).touch()
        deadline = time.monotonic() + STOP_TIMEOUT
        while _alive(state["pid"]) and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            try:  # reap if it is our child
                os.waitpid(state["pid"], os.WNOHANG)
            except ChildProcessError:
                pass
        if _alive(state["pid"]):
            return _text(f"Recorder (pid {state['pid']}) did not finish within {STOP_TIMEOUT:g}s.\n"
                         + _log_tail(state["log"]))

    Path(state["stop_file"]).unlink(missing_ok=True)
    stats = _parse_done(state["log"])
    if not stats:
        return _text("Recording ended without a finished file.\n" + _log_tail(state["log"]))
    return _text("Recording saved.\n" + _describe(stats) +
                 "\n\nNext: export_video (preset 'x' for X, 'preview' for a quick look).")


def _resolve_recording(project_name: str, ref: str | None) -> Path | None:
    if ref and os.path.isfile(ref):
        return Path(ref)
    d = _video_dir(project_name)
    if ref:
        p = d / (ref if ref.endswith(".mov") else f"{ref}.mov")
        return p if p.exists() else None
    # Masters only: a ProRes 'master' export is <name>-master.mov in the same folder.
    movs = sorted((p for p in d.glob("*.mov") if not p.stem.endswith("-master")),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return movs[0] if movs else None


async def _probe(path: Path) -> dict:
    ffprobe = _find_tool("ffprobe")
    if not ffprobe:
        return {}
    proc = await asyncio.create_subprocess_exec(
        ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,avg_frame_rate",
        "-of", "json", str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        return json.loads(out)
    except ValueError:
        return {}


async def handle_export(arguments: dict) -> list[TextContent]:
    project_path = arguments.get("project_path")
    if not project_path:
        return _text("Error: project_path is required")
    project_name, _ = _project(project_path)
    preset_name = arguments.get("preset", "x")
    preset = PRESETS.get(preset_name)
    if not preset:
        return _text(f"Unknown preset '{preset_name}'. Use one of: {', '.join(PRESETS)}")

    state = _read_state(project_name)
    src = _resolve_recording(project_name, arguments.get("recording"))
    if not src:
        return _text("No recording found. Record with start_video_recording / stop_video_recording first.")
    if state and _alive(state["pid"]) and Path(state["path"]) == src:
        return _text(f"{src.name} is still recording. Call stop_video_recording first.")

    ffmpeg = _find_tool("ffmpeg")
    if not ffmpeg:
        return _text("ffmpeg not found (checked PATH and Homebrew/system paths). Install it: brew install ffmpeg.")

    probe = await _probe(src)
    streams = probe.get("streams", [])
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    src_duration = float(probe.get("format", {}).get("duration", 0) or 0)

    start = float(arguments.get("start") or 0)
    end = arguments.get("end")
    end = float(end) if end is not None else src_duration
    length = end - start if end else 0
    if end and length <= 0:
        return _text(f"Empty trim: start {start}s >= end {end}s.")

    ext = ".mov" if preset.get("prores") else ".mp4"
    filename = arguments.get("filename") or f"{src.stem}-{preset_name}{ext}"
    if not filename.endswith(ext):
        filename = Path(filename).stem + ext
    out = _video_dir(project_name) / filename

    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if end and length > 0:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-map", "0:v:0"] + (["-map", "0:a:0"] if has_audio else [])

    if preset.get("prores"):
        cmd += ["-c:v", "prores_videotoolbox", "-profile:v", "hq", "-pix_fmt", "p210le"]
        cmd += ["-c:a", "pcm_s16le"] if has_audio else []
    else:
        w, h = preset["scale"]
        focus = min(max(float(arguments.get("focus_x", 50)), 0), 100) / 100
        # Scale to fill the box, then crop; for a narrower box the slice centers on focus_x.
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={w}:{h}:(iw-{w})*{focus:.3f}:(ih-{h})/2,"
              f"fps={preset['fps']},format=yuv420p")
        cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", str(preset["crf"]),
                "-profile:v", "high", "-fps_mode", "cfr", "-movflags", "+faststart"]
        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
            if preset.get("loudnorm"):
                cmd += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    cmd.append(str(out))

    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0 or not out.exists():
        return _text(f"ffmpeg failed (exit {proc.returncode}):\n{err.decode(errors='replace')[-1500:]}")

    seconds = length if length > 0 else src_duration
    notes = []
    if preset.get("max_seconds") and seconds > preset["max_seconds"]:
        notes.append(f"Note: {seconds:.0f}s is over this platform's {preset['max_seconds']}s limit; trim with start/end.")
    if not has_audio:
        notes.append("Note: the recording has no audio track.")
    size = out.stat().st_size
    return _text(
        f"Exported '{preset_name}': {out}\n{seconds:.1f}s, {size / 1e6:.1f} MB"
        + ("".join("\n" + n for n in notes))
        + "\n\nShow it with SendUserFile (display: render)."
    )


async def handle_list(arguments: dict) -> list[TextContent]:
    project_path = arguments.get("project_path")
    if not project_path:
        return _text("Error: project_path is required")
    project_name, _ = _project(project_path)
    d = _video_dir(project_name)
    files = sorted([p for p in d.iterdir() if p.suffix in (".mov", ".mp4")], key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return _text(f"No recordings in {d}.")
    lines = [f"Recordings in {d} (newest first):", ""]
    for p in files:
        info = await _probe(p)
        v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
        dur = float(info.get("format", {}).get("duration", 0) or 0)
        lines.append(f"  {p.name}  {dur:.1f}s  {v.get('width', '?')}x{v.get('height', '?')}  "
                     f"{p.stat().st_size / 1e6:.1f} MB")
    state = _read_state(project_name)
    if state and _alive(state["pid"]):
        lines += ["", f"Recording now: {state['path']}"]
    return _text("\n".join(lines))


HANDLERS = {
    "start_video_recording": handle_start,
    "stop_video_recording": handle_stop,
    "export_video": handle_export,
    "list_video_recordings": handle_list,
}
