"""
PyClaw Agent Module - Uses Claude Agent SDK
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

from config import GROUPS_DIR, CLAUDE_MODEL, ALLOWED_TOOLS


@dataclass
class AgentResponse:
    success: bool
    result: Optional[str]
    session_id: Optional[str]
    error: Optional[str] = None


async def _query_claude(prompt: str, cwd: str, session_id: Optional[str]) -> AgentResponse:
    """Run a single query via SDK."""
    # Read CLAUDE.md and prepend to system prompt so Claude knows its personality
    from pathlib import Path
    claude_md_path = Path(cwd) / "CLAUDE.md"
    claude_md_content = claude_md_path.read_text() if claude_md_path.exists() else ""

    # Combine CLAUDE.md with essential working directory info
    system_prompt = f"""{claude_md_content}

---
WORKING DIRECTORY: {cwd}
When writing files, use the full absolute path: {cwd}/filename.txt"""

    options = ClaudeAgentOptions(
        model=CLAUDE_MODEL,
        cwd=cwd,
        system_prompt=system_prompt,
        permission_mode="bypassPermissions",
        allowed_tools=ALLOWED_TOOLS,
    )
    if session_id:
        options.resume = session_id

    captured_session_id = None
    response_text = None

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                captured_session_id = message.session_id
                if message.result:
                    response_text = message.result

        return AgentResponse(
            success=response_text is not None,
            result=response_text,
            session_id=captured_session_id,
        )
    except Exception as e:
        return AgentResponse(success=False, result=None, session_id=session_id, error=str(e))


DEFAULT_CLAUDE_MD = """# Assistant

You are a helpful assistant on WhatsApp. Be concise.

## What You Can Do

You have tools to work with files in this folder:
- **Write tool**: Save notes, lists, or any data to files (e.g., `notes.md`, `todos.txt`)
- **Read tool**: Read files you've previously saved
- **WebSearch tool**: Look up current information online

When the user asks you to save, remember, or keep track of something — use the Write tool to create a file.

**REQUIRED:** After creating any file, you MUST use the Edit tool to add it to the "Saved Files" section in this CLAUDE.md file.

## Memories

<!-- Persistent notes about this user/chat -->

## Saved Files

<!-- After creating a file, add it here: "- filename.txt — description" -->
"""


def run_agent(prompt: str, group_folder: str, session_id: Optional[str] = None) -> AgentResponse:
    """Run Claude agent (sync wrapper)."""
    group_dir = GROUPS_DIR / group_folder
    group_dir.mkdir(parents=True, exist_ok=True)

    # Create default CLAUDE.md if missing
    claude_md = group_dir / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(DEFAULT_CLAUDE_MD)

    return asyncio.run(_query_claude(prompt, str(group_dir), session_id))


def build_prompt(message_content: str, sender_name: str, group_name: str) -> str:
    return f"""[WhatsApp message from: {group_name}]
[Sender: {sender_name}]

{message_content}

Reply concisely. This will be sent to WhatsApp."""
