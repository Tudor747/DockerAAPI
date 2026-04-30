import asyncio
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)


QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
CHAT_COLLECTION_NAME = os.getenv("QDRANT_CHAT_COLLECTION", "chat_sessions")

ALLOWED_ROLES = {"user", "assistant", "system"}
MAX_MEMORY_ITEMS = 100

# Qdrant stores data as points. Today we only need the payload for chat history,
# so every session gets the same tiny vector. If we later add semantic search,
# this is the one place to replace it with real embeddings.
DUMMY_VECTOR = [0.0]

qdrant_client = AsyncQdrantClient(url=QDRANT_URL)
_collection_lock = asyncio.Lock()
_collection_ready = False


def _session_point_id(session_id: str) -> str:
    """Qdrant point IDs must be UUIDs or unsigned integers."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"chat-session:{session_id}"))


def _memory_point_id(browser_session_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"user-memory:{browser_session_id}"))


def _sanitize_messages(raw_messages: Any) -> list[dict[str, str]]:
    if not isinstance(raw_messages, list):
        return []

    messages: list[dict[str, str]] = []
    for message in raw_messages:
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        content = message.get("content")
        if role in ALLOWED_ROLES and isinstance(content, str):
            messages.append({"role": role, "content": content})

    return messages


def _sanitize_memory_items(raw_items: Any) -> list[dict[str, str]]:
    if not isinstance(raw_items, list):
        return []

    items: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue

        content = item.get("content")
        source_chat_id = item.get("source_chat_id")
        created_at = item.get("created_at")
        if isinstance(content, str) and content.strip():
            items.append(
                {
                    "content": content,
                    "source_chat_id": source_chat_id if isinstance(source_chat_id, str) else "",
                    "created_at": created_at if isinstance(created_at, str) else "",
                }
            )

    return items


def _chat_payload(
    session_id: str,
    messages: list[dict[str, str]],
    browser_session_id: str | None = None,
) -> dict[str, Any]:
    return {
        "chat": {
            "session_id": session_id,
            "browser_session_id": browser_session_id,
            "messages": messages,
            "message_count": len(messages),
            "updated_at": datetime.now(UTC).isoformat(),
        }
    }


def _memory_payload(browser_session_id: str, items: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "memory": {
            "browser_session_id": browser_session_id,
            "items": items,
            "item_count": len(items),
            "updated_at": datetime.now(UTC).isoformat(),
        }
    }


async def _ensure_collection() -> None:
    global _collection_ready
    if _collection_ready:
        return

    async with _collection_lock:
        if _collection_ready:
            return

        exists = await qdrant_client.collection_exists(CHAT_COLLECTION_NAME)
        if not exists:
            await qdrant_client.create_collection(
                collection_name=CHAT_COLLECTION_NAME,
                vectors_config=VectorParams(size=len(DUMMY_VECTOR), distance=Distance.COSINE),
            )

        _collection_ready = True


async def get_chat_messages(session_id: str) -> list[dict[str, str]]:
    await _ensure_collection()

    points = await qdrant_client.retrieve(
        collection_name=CHAT_COLLECTION_NAME,
        ids=[_session_point_id(session_id)],
        with_payload=True,
    )
    if not points:
        return []

    payload = points[0].payload or {}
    chat = payload.get("chat")
    if isinstance(chat, dict):
        return _sanitize_messages(chat.get("messages"))

    return _sanitize_messages(payload.get("messages"))


async def list_chat_sessions(browser_session_id: str) -> list[dict[str, Any]]:
    await _ensure_collection()

    chat_filter = Filter(
        must=[
            FieldCondition(
                key="chat.browser_session_id",
                match=MatchValue(value=browser_session_id),
            )
        ]
    )
    sessions: list[dict[str, Any]] = []
    offset = None

    while True:
        points, offset = await qdrant_client.scroll(
            collection_name=CHAT_COLLECTION_NAME,
            scroll_filter=chat_filter,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        for point in points:
            payload = point.payload or {}
            chat = payload.get("chat")
            if not isinstance(chat, dict):
                continue

            session_id = chat.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                continue

            messages = _sanitize_messages(chat.get("messages"))
            updated_at = chat.get("updated_at")
            sessions.append(
                {
                    "session_id": session_id,
                    "messages": messages,
                    "message_count": len(messages),
                    "updated_at": updated_at if isinstance(updated_at, str) else "",
                }
            )

        if offset is None:
            break

    return sorted(sessions, key=lambda session: session["updated_at"], reverse=True)


async def save_chat_messages(
    session_id: str,
    messages: list[dict[str, str]],
    browser_session_id: str | None = None,
) -> None:
    await _ensure_collection()

    await qdrant_client.upsert(
        collection_name=CHAT_COLLECTION_NAME,
        points=[
            PointStruct(
                id=_session_point_id(session_id),
                vector=DUMMY_VECTOR,
                payload=_chat_payload(session_id, messages, browser_session_id),
            )
        ],
    )


async def delete_chat_session(session_id: str) -> None:
    await _ensure_collection()

    await qdrant_client.delete(
        collection_name=CHAT_COLLECTION_NAME,
        points_selector=PointIdsList(points=[_session_point_id(session_id)]),
    )


async def get_user_memory_items(browser_session_id: str) -> list[dict[str, str]]:
    await _ensure_collection()

    points = await qdrant_client.retrieve(
        collection_name=CHAT_COLLECTION_NAME,
        ids=[_memory_point_id(browser_session_id)],
        with_payload=True,
    )
    if not points:
        return []

    payload = points[0].payload or {}
    memory = payload.get("memory")
    if not isinstance(memory, dict):
        return []

    return _sanitize_memory_items(memory.get("items"))


async def remember_user_message(
    browser_session_id: str,
    source_chat_id: str,
    content: str,
) -> None:
    normalized_content = content.strip()
    if not normalized_content:
        return

    items = await get_user_memory_items(browser_session_id)
    items.append(
        {
            "content": normalized_content,
            "source_chat_id": source_chat_id,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    items = items[-MAX_MEMORY_ITEMS:]

    await qdrant_client.upsert(
        collection_name=CHAT_COLLECTION_NAME,
        points=[
            PointStruct(
                id=_memory_point_id(browser_session_id),
                vector=DUMMY_VECTOR,
                payload=_memory_payload(browser_session_id, items),
            )
        ],
    )
