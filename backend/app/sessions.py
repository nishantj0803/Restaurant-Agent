import asyncio
import time
from dataclasses import dataclass, field
from uuid import uuid4

from .schemas import Preferences, Result, Source


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid4().hex)
    updated: float = field(default_factory=time.monotonic)
    history: list[dict] = field(default_factory=list)
    preferences: Preferences | None = None
    result: Result | None = None
    sources: dict[str, Source] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def remember(self, role: str, content: str):
        self.history.append({"role": role, "content": content[:4000]})
        self.history = self.history[-16:]
        self.updated = time.monotonic()


class Sessions:
    def __init__(self):
        self.items: dict[str, Session] = {}

    def get(self, session_id: str | None) -> Session | None:
        now = time.monotonic()
        self.items = {
            key: value
            for key, value in self.items.items()
            if now - value.updated < 3600 or value.lock.locked()
        }
        if session_id:
            return self.items.get(session_id)
        if len(self.items) >= 32:
            idle = [value for value in self.items.values() if not value.lock.locked()]
            if not idle:
                return None
            self.items.pop(min(idle, key=lambda value: value.updated).id)
        session = Session()
        self.items[session.id] = session
        return session
