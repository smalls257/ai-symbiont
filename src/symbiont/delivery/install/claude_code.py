"""Claude Code: hooks in the project's .claude/settings.json and the MCP server in .mcp.json."""

from symbiont.delivery.hooks import HookEvent, NoteStyle
from symbiont.delivery.install.hook_config import hooks_block, merge_json
from symbiont.delivery.install.transaction import HarnessInstall

HARNESS = "claude_code"
EVENTS = (
    HookEvent.SESSION_START,
    HookEvent.USER_PROMPT_SUBMIT,
    HookEvent.POST_TOOL_USE,
    HookEvent.POST_TOOL_USE_FAILURE,
)
SETTINGS = ".claude/settings.json"
MCP_CONFIG = ".mcp.json"


def claude_code_install(style: NoteStyle) -> HarnessInstall:
    """Hooks and the MCP server for Claude Code in one project."""
    mcp = {"mcpServers": {"symbiont": {"command": "symbiont", "args": ["mcp"]}}}
    return HarnessInstall(
        HARNESS,
        {
            SETTINGS: merge_json(SETTINGS, hooks_block(EVENTS, HARNESS, style)),
            MCP_CONFIG: merge_json(MCP_CONFIG, mcp),
        },
    )
