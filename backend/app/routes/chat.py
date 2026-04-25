import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from openai import APIConnectionError, APIStatusError, RateLimitError
from fastapi.responses import StreamingResponse

from app.db.mongo import get_chat_messages, save_chat_messages
from app.models.chat import ChatMessage, ChatRequest, ChatResponse, ChatSession
from app.services.ai import generate_assistant_reply, stream_assistant_reply


router = APIRouter(prefix="/chat", tags=["chat"])


def _to_message_models(messages: list[dict[str, str]]) -> list[ChatMessage]:
    result: list[ChatMessage] = []
    for message in messages:
        result.append(ChatMessage(role=message["role"], content=message["content"]))
    return result


def _ai_error_message(exc: Exception) -> str:
    if isinstance(exc, RateLimitError):
        return "OpenAI quota exceeded. Check billing and usage limits for your API key."
    if isinstance(exc, APIConnectionError):
        return "Could not connect to OpenAI. Check OPENAI_BASE_URL and network access."
    if isinstance(exc, APIStatusError):
        return f"OpenAI request failed: {exc}"
    return f"AI provider error: {exc}"


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
    history.append({"role": "user", "content": request.message})

    try:
        assistant_content = await generate_assistant_reply(history)
    except Exception as exc:
        _raise_ai_http_exception(exc)

    history.append({"role": "assistant", "content": assistant_content})

    await save_chat_messages(request.session_id, history)

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
    history.append({"role": "user", "content": request.message})

    async def stream() -> AsyncGenerator[str, None]:
        assistant_chunks: list[str] = []
        try:
            async for token in stream_assistant_reply(history):
                assistant_chunks.append(token)
                yield json.dumps({"type": "delta", "content": token}) + "\n"

            assistant_content = "".join(assistant_chunks)
            history.append({"role": "assistant", "content": assistant_content})
            await save_chat_messages(request.session_id, history)
            yield json.dumps({"type": "done", "session_id": request.session_id}) + "\n"
        except Exception as exc:  # pragma: no cover - runtime failure path
            yield json.dumps({"type": "error", "message": _ai_error_message(exc)}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
