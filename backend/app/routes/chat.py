import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from openai import APIConnectionError, APIStatusError, RateLimitError
from fastapi.responses import StreamingResponse

from app.db.qdrant import (
    get_chat_messages,
    get_user_memory_items,
    remember_user_message,
    save_chat_messages,
)
from app.models.chat import ChatMessage, ChatRequest, ChatResponse, ChatSession
from app.services.ai import (
    generate_assistant_reply,
    get_ai_provider_label,
    stream_assistant_reply,
)


router = APIRouter(prefix="/chat", tags=["chat"])
MEMORY_ITEMS_IN_PROMPT = 30


def _user_message(content: str) -> dict[str, str]:
    return {"role": "user", "content": content}


def _assistant_message(content: str) -> dict[str, str]:
    return {"role": "assistant", "content": content}


def _to_message_models(messages: list[dict[str, str]]) -> list[ChatMessage]:
    return [ChatMessage(role=message["role"], content=message["content"]) for message in messages]


def _browser_session_id(request: ChatRequest) -> str:
    return request.browser_session_id or request.session_id


def _with_user_memory(
    messages: list[dict[str, str]],
    memory_items: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not memory_items:
        return messages

    remembered_facts = "\n".join(
        f"- {item['content']}" for item in memory_items[-MEMORY_ITEMS_IN_PROMPT:]
    )
    return [
        {
            "role": "system",
            "content": (
                "The following notes are persistent memory about this user from previous "
                "conversations. Use them when relevant, but do not recite them unless the "
                f"user asks.\n{remembered_facts}"
            ),
        },
        *messages,
    ]


def _ai_error_message(exc: Exception) -> str:
    provider = get_ai_provider_label()
    if isinstance(exc, RateLimitError):
        return f"{provider} quota exceeded. Check billing and usage limits for your API key."
    if isinstance(exc, APIConnectionError):
        return f"Could not connect to {provider}. Check provider base URL and network access."
    if isinstance(exc, APIStatusError):
        return f"{provider} request failed: {exc}"
    return f"{provider} provider error: {exc}"


def _raise_ai_http_exception(exc: Exception) -> None:
    status_code = 502
    if isinstance(exc, RateLimitError):
        status_code = 429
    elif isinstance(exc, APIStatusError) and exc.status_code:
        status_code = exc.status_code if 400 <= exc.status_code <= 599 else 502
    raise HTTPException(status_code=status_code, detail=_ai_error_message(exc))


@router.get("/{session_id}", response_model=ChatSession)
async def get_chat(session_id: str) -> ChatSession:
    messages = await get_chat_messages(session_id)
    return ChatSession(session_id=session_id, messages=_to_message_models(messages))


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    history = await get_chat_messages(request.session_id)
    history.append(_user_message(request.message))
    browser_session_id = _browser_session_id(request)
    memory_items = await get_user_memory_items(browser_session_id)

    try:
        assistant_content = await generate_assistant_reply(_with_user_memory(history, memory_items))
    except Exception as exc:
        _raise_ai_http_exception(exc)

    history.append(_assistant_message(assistant_content))
    await remember_user_message(browser_session_id, request.session_id, request.message)
    await save_chat_messages(request.session_id, history, browser_session_id)

    return ChatResponse(
        session_id=request.session_id,
        message=assistant_content,
        messages=_to_message_models(history),
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    history = await get_chat_messages(request.session_id)
    history.append(_user_message(request.message))
    browser_session_id = _browser_session_id(request)
    memory_items = await get_user_memory_items(browser_session_id)
    messages_for_model = _with_user_memory(history, memory_items)

    async def stream() -> AsyncGenerator[str, None]:
        assistant_chunks: list[str] = []
        try:
            async for token in stream_assistant_reply(messages_for_model):
                assistant_chunks.append(token)
                yield json.dumps({"type": "delta", "content": token}) + "\n"

            assistant_content = "".join(assistant_chunks)
            history.append(_assistant_message(assistant_content))
            await remember_user_message(browser_session_id, request.session_id, request.message)
            await save_chat_messages(request.session_id, history, browser_session_id)
            yield json.dumps({"type": "done", "session_id": request.session_id}) + "\n"
        except Exception as exc:  # pragma: no cover - runtime failure path
            yield json.dumps({"type": "error", "message": _ai_error_message(exc)}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
