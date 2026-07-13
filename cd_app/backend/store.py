"""MongoDB-backed conversation store.

Two collections in the ``christian_doctrine`` database:
  conversations: one doc per session (owner, title, timestamps, archived, msg_seq)
  messages:      one doc per rendered message (session_id, owner, role, text, tools, seq)

This is the durable, queryable history and the ownership index. It is separate
from the Agent SDK's own on disk session transcripts, which still exist (on a
volume) so the model can resume a conversation with full context. Ownership is
authorized here so a user only ever sees their own conversations.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument


class ConversationStore:
    def __init__(self, mongo_url: str, db_name: str) -> None:
        self._client: AsyncIOMotorClient = AsyncIOMotorClient(mongo_url)
        db = self._client[db_name]
        self.conversations = db.conversations
        self.messages = db.messages

    async def ensure_indexes(self) -> None:
        await self.conversations.create_index("session_id", unique=True)
        await self.conversations.create_index([("owner", 1), ("archived", 1), ("updated_at", -1)])
        await self.messages.create_index([("session_id", 1), ("seq", 1)])

    async def ping(self) -> None:
        await self._client.admin.command("ping")

    async def record_conversation(self, session_id: str, owner: str, title: str, now: str) -> None:
        await self.conversations.update_one(
            {"session_id": session_id},
            {
                "$setOnInsert": {
                    "owner": owner,
                    "title": title[:80],
                    "created_at": now,
                    "archived": False,
                    "msg_seq": 0,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )

    async def owner_of(self, session_id: str) -> str | None:
        doc = await self.conversations.find_one({"session_id": session_id}, {"owner": 1})
        return doc["owner"] if doc else None

    async def list_for(self, owner: str) -> list[dict[str, Any]]:
        cur = self.conversations.find(
            {"owner": owner, "archived": False},
            {"_id": 0, "session_id": 1, "title": 1, "updated_at": 1},
        ).sort("updated_at", -1)
        return [
            {
                "session_id": d["session_id"],
                "title": d.get("title", "Untitled"),
                "last_modified": d.get("updated_at", ""),
            }
            async for d in cur
        ]

    async def set_title(self, session_id: str, title: str) -> None:
        await self.conversations.update_one(
            {"session_id": session_id}, {"$set": {"title": title[:80]}}
        )

    async def archive(self, session_id: str) -> None:
        await self.conversations.update_one(
            {"session_id": session_id}, {"$set": {"archived": True}}
        )

    async def append_message(
        self, session_id: str, owner: str, role: str, text: str, tools: list[str], now: str
    ) -> None:
        # Per-conversation monotonic sequence, so display order is deterministic.
        doc = await self.conversations.find_one_and_update(
            {"session_id": session_id},
            {"$inc": {"msg_seq": 1}, "$set": {"updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        seq = doc["msg_seq"] if doc else 0
        await self.messages.insert_one(
            {
                "session_id": session_id,
                "owner": owner,
                "role": role,
                "text": text,
                "tools": tools,
                "ts": now,
                "seq": seq,
            }
        )

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        cur = self.messages.find(
            {"session_id": session_id}, {"_id": 0, "role": 1, "text": 1, "tools": 1}
        ).sort("seq", 1)
        return [d async for d in cur]

    def close(self) -> None:
        self._client.close()
