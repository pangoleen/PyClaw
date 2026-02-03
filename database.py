"""
PyClaw Database Module

Handles all SQLite operations for storing and retrieving messages.

The database has two tables:
- chats: Metadata about each WhatsApp chat (group or individual)
- messages: All messages from registered groups
"""

import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class Message:
    """A single WhatsApp message."""
    id: str
    chat_jid: str
    sender: str
    sender_name: str
    content: str
    timestamp: str
    is_from_me: bool


class Database:
    """
    SQLite database for storing WhatsApp messages.

    We store messages so we can:
    1. Query "what's new since timestamp X?"
    2. Have a history of conversations
    """

    def __init__(self, db_path: Path):
        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connect to SQLite (creates file if it doesn't exist)
        # check_same_thread=False allows use from multiple threads
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Access columns by name

        self._create_tables()

    def _create_tables(self):
        """Create the database schema if it doesn't exist."""
        self.conn.executescript("""
            -- Chats table: one row per WhatsApp chat
            CREATE TABLE IF NOT EXISTS chats (
                jid TEXT PRIMARY KEY,           -- WhatsApp's unique ID for the chat
                name TEXT,                       -- Display name
                last_message_time TEXT           -- When we last saw a message
            );

            -- Messages table: all messages from registered groups
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT,                         -- WhatsApp's message ID
                chat_jid TEXT,                   -- Which chat this belongs to
                sender TEXT,                     -- Sender's JID (phone number)
                sender_name TEXT,                -- Sender's display name
                content TEXT,                    -- The actual message text
                timestamp TEXT,                  -- ISO timestamp
                is_from_me INTEGER,              -- 1 if we sent it, 0 otherwise
                PRIMARY KEY (id, chat_jid)
            );

            -- Index for fast timestamp queries
            CREATE INDEX IF NOT EXISTS idx_messages_timestamp
            ON messages(timestamp);

            -- Index for fast chat lookups
            CREATE INDEX IF NOT EXISTS idx_messages_chat
            ON messages(chat_jid);
        """)
        self.conn.commit()

    def store_message(
        self,
        msg_id: str,
        chat_jid: str,
        sender: str,
        sender_name: str,
        content: str,
        timestamp: str,
        is_from_me: bool
    ) -> None:
        """
        Store a message in the database.

        Uses INSERT OR REPLACE so we don't get duplicates if we
        see the same message twice (WhatsApp can send duplicates).
        """
        # Update chat metadata
        self.conn.execute("""
            INSERT OR REPLACE INTO chats (jid, name, last_message_time)
            VALUES (?, ?, ?)
        """, (chat_jid, chat_jid, timestamp))

        # Store the message
        self.conn.execute("""
            INSERT OR REPLACE INTO messages
            (id, chat_jid, sender, sender_name, content, timestamp, is_from_me)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, chat_jid, sender, sender_name, content, timestamp, 1 if is_from_me else 0))

        self.conn.commit()

    def get_new_messages(
        self,
        chat_jids: list[str],
        since_timestamp: str,
        exclude_sender_prefix: Optional[str] = None
    ) -> list[Message]:
        """
        Get all messages newer than `since_timestamp` from the specified chats.

        Args:
            chat_jids: List of chat JIDs to query
            since_timestamp: ISO timestamp - only get messages after this
            exclude_sender_prefix: If set, exclude messages where content starts with this
                                   (used to filter out our own bot responses)

        Returns:
            List of Message objects, ordered by timestamp
        """
        if not chat_jids:
            return []

        # Build query with placeholders for each JID
        placeholders = ",".join("?" * len(chat_jids))

        query = f"""
            SELECT id, chat_jid, sender, sender_name, content, timestamp, is_from_me
            FROM messages
            WHERE timestamp > ?
              AND chat_jid IN ({placeholders})
            ORDER BY timestamp
        """

        cursor = self.conn.execute(query, [since_timestamp] + chat_jids)

        messages = []
        for row in cursor:
            # Skip our own bot messages (they start with "PyClaw:")
            if exclude_sender_prefix and row["content"].startswith(exclude_sender_prefix):
                continue

            messages.append(Message(
                id=row["id"],
                chat_jid=row["chat_jid"],
                sender=row["sender"],
                sender_name=row["sender_name"],
                content=row["content"],
                timestamp=row["timestamp"],
                is_from_me=bool(row["is_from_me"])
            ))

        return messages

    def close(self):
        """Close the database connection."""
        self.conn.close()
