"""
PyClaw Configuration

All the constants and settings in one place.
"""

import os
import re
from pathlib import Path

# === ASSISTANT SETTINGS ===

# The name of your assistant - used for triggers and response prefixes
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "PyClaw")

# Pattern to detect when someone is talking to the assistant
# e.g., "@PyClaw what's the weather?" matches, "hello everyone" doesn't
TRIGGER_PATTERN = re.compile(rf"^@{ASSISTANT_NAME}\b", re.IGNORECASE)

# Command to clear conversation history
CLEAR_COMMAND = "/clear"

# Command to update personality/instructions
PERSONALITY_COMMAND = "/personality"

# === CLAUDE AGENT ===

# Model to use for the agent
CLAUDE_MODEL = "haiku"

# Tools the agent is allowed to use (no Bash for security)
ALLOWED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"]

# === TIMING ===

# How often to check for new messages (in seconds)
POLL_INTERVAL = 2

# === PATHS ===

# Project root directory
PROJECT_ROOT = Path(__file__).parent

# Where we store persistent data
STORE_DIR = PROJECT_ROOT / "store"
DATA_DIR = PROJECT_ROOT / "data"
GROUPS_DIR = PROJECT_ROOT / "groups"

# Specific files
DATABASE_PATH = STORE_DIR / "messages.db"
AUTH_DIR = STORE_DIR / "auth"
SESSIONS_FILE = DATA_DIR / "sessions.json"
REGISTERED_GROUPS_FILE = DATA_DIR / "registered_groups.json"
STATE_FILE = DATA_DIR / "router_state.json"
