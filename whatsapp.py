"""
PyClaw WhatsApp Module

Handles connection to WhatsApp using the Neonize library.
"""

from pathlib import Path
from typing import Callable, Optional
from dataclasses import dataclass
from datetime import datetime

from neonize.client import NewClient
from neonize.events import MessageEv, ConnectedEv
from neonize.utils import build_jid

from config import AUTH_DIR


@dataclass
class IncomingMessage:
    """A WhatsApp message received by our bot."""
    id: str
    chat_jid: str
    sender_jid: str
    sender_name: str
    content: str
    timestamp: str
    is_from_me: bool


MessageHandler = Callable[[IncomingMessage], None]


class WhatsAppClient:
    def __init__(self, session_name: str = "pyclaw"):
        AUTH_DIR.mkdir(parents=True, exist_ok=True)
        db_path = AUTH_DIR / f"{session_name}.db"
        self._client = NewClient(str(db_path))
        self._message_handler: Optional[MessageHandler] = None
        self._connected = False
        self._setup_events()

    def _setup_events(self):
        @self._client.event(ConnectedEv)
        def on_connected(client: NewClient, event: ConnectedEv):
            self._connected = True
            print("✓ Connected to WhatsApp!")

        @self._client.event(MessageEv)
        def on_message(client: NewClient, event: MessageEv):
            if self._message_handler is None:
                return

            # Extract message content (capitalized attributes!)
            content = self._extract_content(event)
            if content is None:
                return

            # Build JID from Chat object
            chat = event.Info.MessageSource.Chat
            chat_jid = f"{chat.User}@{chat.Server}"

            sender = event.Info.MessageSource.Sender
            sender_jid = f"{sender.User}@{sender.Server}"

            # Convert timestamp (milliseconds to ISO)
            ts = datetime.fromtimestamp(event.Info.Timestamp / 1000).isoformat()

            msg = IncomingMessage(
                id=event.Info.ID,
                chat_jid=chat_jid,
                sender_jid=sender_jid,
                sender_name=event.Info.Pushname or "Unknown",
                content=content,
                timestamp=ts,
                is_from_me=event.Info.MessageSource.IsFromMe,
            )

            self._message_handler(msg)

    def _extract_content(self, event: MessageEv) -> Optional[str]:
        msg = event.Message

        if msg.conversation:
            return msg.conversation
        if msg.extendedTextMessage and msg.extendedTextMessage.text:
            return msg.extendedTextMessage.text
        if msg.imageMessage and msg.imageMessage.caption:
            return msg.imageMessage.caption
        if msg.videoMessage and msg.videoMessage.caption:
            return msg.videoMessage.caption

        return None

    def on_message(self, handler: MessageHandler):
        self._message_handler = handler

    def send_message(self, chat_jid: str, text: str):
        # Parse the JID - format is "user@server"
        parts = chat_jid.split("@")
        if len(parts) == 2:
            from neonize.proto.Neonize_pb2 import JID
            jid = JID(
                User=parts[0],
                Server=parts[1],
                RawAgent=0,
                Device=0,
                Integrator=0,
                IsEmpty=False
            )
            self._client.send_message(jid, text)
        else:
            print(f"[WhatsApp] Invalid JID format: {chat_jid}")

    def connect(self):
        print("Connecting to WhatsApp...")
        print("(Scan the QR code with WhatsApp if this is your first time)")
        print()
        self._client.connect()

    @property
    def is_connected(self) -> bool:
        return self._connected
