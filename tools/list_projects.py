"""
list_running_projects tool - List all running Solar2D Simulator projects.
"""

from mcp.types import Tool, TextContent

from utils import running_projects


TOOL = Tool(
    name="list_running_projects",
    description="List all currently running Solar2D Simulator projects tracked by this server.",
    inputSchema={
        "type": "object",
        "properties": {}
    }
)


async def handle(arguments: dict) -> list[TextContent]:
    """Handle list_running_projects tool call."""
    if not running_projects:
        return [TextContent(
            type="text",
            text="No Solar2D Simulator projects are currently running."
        )]

    projects_info = []
    for project_dir, info in running_projects.items():
        # Check if process is still running
        process = info["process"]
        status = "running" if process.poll() is None else "stopped"

        projects_info.append(
            f"Project: {project_dir}\n"
            f"  Main: {info['main_lua']}\n"
            f"  PID: {info['pid']}\n"
            f"  Status: {status}\n"
            f"  Log: {info['log_file']}"
        )

    return [TextContent(
        type="text",
        text="Running Solar2D Projects:\n\n" + "\n\n".join(projects_info)
    )]
