from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    browser_session_id: str | None = Field(default=None, min_length=1)


class ChatResponse(BaseModel):
    session_id: str
    message: str
    messages: list[ChatMessage]


class ChatSession(BaseModel):
    session_id: str
    messages: list[ChatMessage]


class ChatSummary(BaseModel):
    session_id: str
    title: str
    message_count: int
    updated_at: str = ""


class ChatListResponse(BaseModel):
    sessions: list[ChatSummary]
