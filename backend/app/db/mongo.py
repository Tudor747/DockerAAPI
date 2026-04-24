import os

from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URI = os.getenv("MONGO_URI", "mongodb://db:27017")
DB_NAME = os.getenv("CHAT_DB_NAME", "chatapp")

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]
chat_collection = db["chats"]

ALLOWED_ROLES = {"user", "assistant", "system"}


def _sanitize_messages(raw_messages: list[dict]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for message in raw_messages:
        role = message.get("role")
        content = message.get("content")
        if role in ALLOWED_ROLES and isinstance(content, str):
            messages.append({"role": role, "content": content})
    return messages


async def get_chat_messages(session_id: str) -> list[dict[str, str]]:
    document = await chat_collection.find_one({"session_id": session_id})
    if not document:
        return []
    raw_messages = document.get("messages", [])
    return _sanitize_messages(raw_messages)


async def save_chat_messages(session_id: str, messages: list[dict[str, str]]) -> None:
    await chat_collection.update_one(
        {"session_id": session_id},
        {"$set": {"session_id": session_id, "messages": messages}},
        upsert=True,
    )

