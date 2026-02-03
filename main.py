"""
PyClaw - Personal Claude Assistant via WhatsApp

This is the main entry point that ties everything together:
1. Connects to WhatsApp (via Neonize)
2. Stores messages in SQLite
3. Polls for new messages
4. Triggers Claude agent when someone @mentions PyClaw
5. Sends the response back to WhatsApp

Architecture:
    WhatsApp (Neonize) → stores → SQLite Database
                                      ↓
                              Poll Loop (every 2s)
                                      ↓
                              Check trigger (@PyClaw)
                                      ↓
                              Claude Agent SDK
                                      ↓
                              Send response → WhatsApp
"""

import json
import time
import signal
import sys
from datetime import datetime
from typing import Optional

from config import (
    ASSISTANT_NAME,
    TRIGGER_PATTERN,
    CLEAR_COMMAND,
    PERSONALITY_COMMAND,
    POLL_INTERVAL,
    DATABASE_PATH,
    SESSIONS_FILE,
    REGISTERED_GROUPS_FILE,
    STATE_FILE,
    DATA_DIR,
    GROUPS_DIR,
)
from database import Database, Message
from whatsapp import WhatsAppClient, IncomingMessage
from agent import run_agent, build_prompt


# === STATE MANAGEMENT ===
# These are loaded from files on startup and saved after each message

# Last timestamp we processed — so we don't re-process old messages
last_timestamp: str = ""

# Session IDs per group folder — for Claude conversation continuity
sessions: dict[str, str] = {}

# Registered groups — which chats we should respond to
registered_groups: dict[str, dict] = {}


def load_json(path, default):
    """Load JSON file, returning default if it doesn't exist."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        print(f"Warning: Failed to load {path}: {e}")
    return default


def save_json(path, data):
    """Save data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def load_state():
    """Load all state from files."""
    global last_timestamp, sessions, registered_groups

    state = load_json(STATE_FILE, {})
    last_timestamp = state.get("last_timestamp", "")

    sessions = load_json(SESSIONS_FILE, {})
    registered_groups = load_json(REGISTERED_GROUPS_FILE, {})

    print(f"Loaded state: {len(registered_groups)} registered groups")
    print(f"Last timestamp: {last_timestamp or '(none — will process all new messages)'}")


def save_state():
    """Save current state to files."""
    save_json(STATE_FILE, {"last_timestamp": last_timestamp})
    save_json(SESSIONS_FILE, sessions)


# === MESSAGE HANDLING ===

def process_message(msg: Message, db: Database, whatsapp: WhatsAppClient):
    """
    Process a single message — check trigger, run agent, send response.

    This is the core logic:
    1. Check if message is from a registered group
    2. Handle /clear command (resets conversation)
    3. Handle /personality command (updates CLAUDE.md)
    4. Check if message matches trigger pattern (@PyClaw)
    5. Strip the trigger from the message
    6. Build prompt with context
    7. Run Claude agent
    8. Send response back to WhatsApp
    9. Save session for conversation continuity
    """
    global last_timestamp, sessions

    # Get group config
    group = registered_groups.get(msg.chat_jid)
    if not group:
        return  # Not a registered group, ignore

    content = msg.content.strip()
    group_folder = group["folder"]

    # Handle /clear command — resets the conversation
    if content.lower() == CLEAR_COMMAND:
        if group_folder in sessions:
            del sessions[group_folder]
            save_state()
            print(f"Session cleared for {group['name']}")
        whatsapp.send_message(msg.chat_jid, f"*{ASSISTANT_NAME}:* Conversation cleared! Starting fresh.")
        return

    # Handle /personality command — updates CLAUDE.md (preserves Memories and Saved Files)
    if content.lower().startswith(PERSONALITY_COMMAND):
        new_instructions = content[len(PERSONALITY_COMMAND):].strip()
        if not new_instructions:
            whatsapp.send_message(msg.chat_jid, f"*{ASSISTANT_NAME}:* Usage: /personality <instructions>")
            return

        claude_md_path = GROUPS_DIR / group_folder / "CLAUDE.md"
        claude_md_path.parent.mkdir(parents=True, exist_ok=True)

        # Preserve existing Memories and Saved Files sections
        memories = "<!-- Persistent notes about this user/chat -->"
        saved_files = "<!-- After creating a file, add it here: \"- filename.txt — description\" -->"

        if claude_md_path.exists():
            existing = claude_md_path.read_text()
            # Extract Memories section
            if "## Memories" in existing:
                memories_start = existing.find("## Memories") + len("## Memories")
                memories_end = existing.find("## Saved Files") if "## Saved Files" in existing else len(existing)
                memories = existing[memories_start:memories_end].strip()
            # Extract Saved Files section
            if "## Saved Files" in existing:
                saved_files_start = existing.find("## Saved Files") + len("## Saved Files")
                saved_files = existing[saved_files_start:].strip()

        new_content = f"""# Assistant

{new_instructions}

## What You Can Do

You have tools to work with files in this folder:
- **Write tool**: Save notes, lists, or any data to files (e.g., `notes.md`, `todos.txt`)
- **Read tool**: Read files you've previously saved
- **WebSearch tool**: Look up current information online

When the user asks you to save, remember, or keep track of something — use the Write tool to create a file.

**REQUIRED:** After creating any file, you MUST use the Edit tool to add it to the "Saved Files" section in this CLAUDE.md file.

## Memories

{memories}

## Saved Files

{saved_files}
"""
        claude_md_path.write_text(new_content)

        whatsapp.send_message(msg.chat_jid, f"*{ASSISTANT_NAME}:* Personality updated!")
        print(f"Personality updated for {group['name']}")
        return

    # Check if message matches trigger pattern
    if not TRIGGER_PATTERN.match(content):
        return  # Doesn't start with @PyClaw, ignore

    # Strip the trigger from the message
    # "@PyClaw what's the weather?" → "what's the weather?"
    prompt_text = TRIGGER_PATTERN.sub("", content).strip()
    if not prompt_text:
        return  # Empty message after stripping trigger

    print(f"\n{'='*50}")
    print(f"Processing message from {group['name']}")
    print(f"Sender: {msg.sender_name}")
    print(f"Message: {prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}")

    # Build the full prompt with context
    prompt = build_prompt(
        message_content=prompt_text,
        sender_name=msg.sender_name,
        group_name=group["name"],
    )

    # Get existing session for this group (for conversation continuity)
    session_id = sessions.get(group_folder)

    # Run the Claude agent
    print(f"Running Claude agent...")
    response = run_agent(prompt, group_folder, session_id)

    if response.success and response.result:
        # Save the new session ID for next time
        if response.session_id:
            sessions[group_folder] = response.session_id

        # Send response to WhatsApp
        reply = f"*{ASSISTANT_NAME}:* {response.result}"
        whatsapp.send_message(msg.chat_jid, reply)
        print(f"Response sent: {response.result[:100]}{'...' if len(response.result) > 100 else ''}")
    else:
        # Something went wrong
        error_msg = f"*{ASSISTANT_NAME}:* Sorry, I encountered an error. Please try again."
        whatsapp.send_message(msg.chat_jid, error_msg)
        print(f"Error: {response.error}")

    print(f"{'='*50}\n")


def message_loop(db: Database, whatsapp: WhatsAppClient):
    """
    Main polling loop — check for new messages every POLL_INTERVAL seconds.

    This runs continuously:
    1. Query database for messages newer than last_timestamp
    2. For each message, call process_message()
    3. Update last_timestamp after successful processing
    4. Save state to disk
    5. Sleep for POLL_INTERVAL seconds
    6. Repeat
    """
    global last_timestamp

    print(f"\nPyClaw is running! (trigger: @{ASSISTANT_NAME})")
    print(f"Polling for messages every {POLL_INTERVAL} seconds...")
    print(f"Press Ctrl+C to stop\n")

    while True:
        try:
            # Get list of registered group JIDs
            jids = list(registered_groups.keys())

            if jids:
                # Query for new messages
                messages = db.get_new_messages(
                    chat_jids=jids,
                    since_timestamp=last_timestamp,
                    exclude_sender_prefix=f"*{ASSISTANT_NAME}:*",  # Skip our own messages
                )

                for msg in messages:
                    try:
                        process_message(msg, db, whatsapp)
                        # Only advance timestamp after successful processing
                        last_timestamp = msg.timestamp
                        save_state()
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        # Don't advance timestamp — will retry next loop
                        break

        except Exception as e:
            print(f"Error in message loop: {e}")

        # Wait before next poll
        time.sleep(POLL_INTERVAL)


# === WHATSAPP EVENT HANDLERS ===

def on_whatsapp_message(msg: IncomingMessage, db: Database):
    """
    Called when WhatsApp receives a message.

    We store it in the database immediately. The polling loop
    will pick it up and process it.
    """
    # Only store messages from registered groups
    if msg.chat_jid not in registered_groups:
        print(f"[Unregistered] {msg.chat_jid} — {msg.sender_name}: {msg.content[:30]}")
        return

    print(f"[Message] {msg.sender_name}: {msg.content[:50]}")

    db.store_message(
        msg_id=msg.id,
        chat_jid=msg.chat_jid,
        sender=msg.sender_jid,
        sender_name=msg.sender_name,
        content=msg.content,
        timestamp=msg.timestamp,
        is_from_me=msg.is_from_me,
    )


# === MAIN ===

def main():
    """Main entry point."""
    print(f"""
    ╔═══════════════════════════════════════╗
    ║              PyClaw                   ║
    ║   Personal Claude Assistant           ║
    ╚═══════════════════════════════════════╝
    """)

    # Load saved state
    load_state()

    # Initialize database
    print("Initializing database...")
    db = Database(DATABASE_PATH)

    # Initialize WhatsApp client
    print("Initializing WhatsApp...")
    whatsapp = WhatsAppClient()

    # Register message handler (stores messages to DB)
    whatsapp.on_message(lambda msg: on_whatsapp_message(msg, db))

    # Handle graceful shutdown
    def shutdown(signum, frame):
        print("\nShutting down...")
        db.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Connect to WhatsApp (this will show QR code on first run)
    # This runs in background, receiving messages
    import threading
    whatsapp_thread = threading.Thread(target=whatsapp.connect, daemon=True)
    whatsapp_thread.start()

    # Wait a moment for WhatsApp to connect
    print("Waiting for WhatsApp connection...")
    time.sleep(5)

    # Start the message processing loop (blocks)
    message_loop(db, whatsapp)


if __name__ == "__main__":
    main()
