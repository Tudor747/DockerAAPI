import os
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from app.models.llama import DEFAULT_LLAMA_BASE_URL, DEFAULT_LLAMA_MODEL, load_llama_config

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").strip().lower()
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a helpful assistant.")
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip()
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_BASE_URL = (
    os.getenv("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta/openai/"
).strip()

_client: AsyncOpenAI | None = None
_model_name: str | None = None


def _provider_label(provider: str) -> str:
    if provider == "openai":
        return "OpenAI"
    if provider == "llama":
        return "Llama"
    if provider == "gemini":
        return "Gemini"
    return provider


def get_ai_provider_label() -> str:
    return _provider_label(AI_PROVIDER)


def _build_client_and_model() -> tuple[AsyncOpenAI, str]:
    if AI_PROVIDER == "llama":
        llama_config = load_llama_config()
        if not llama_config:
            raise RuntimeError("LLAMA_API_KEY is required when AI_PROVIDER=llama.")
        return (
            AsyncOpenAI(
                api_key=llama_config.api_key,
                base_url=llama_config.base_url,
            ),
            llama_config.model,
        )

    if AI_PROVIDER == "openai":
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise RuntimeError("OPENAI_API_KEY is required when AI_PROVIDER=openai.")

        base_url = OPENAI_BASE_URL or OPENAI_DEFAULT_BASE_URL
        return (
            AsyncOpenAI(api_key=openai_key, base_url=base_url),
            OPENAI_MODEL_NAME,
        )

    if AI_PROVIDER == "gemini":
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not gemini_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required when AI_PROVIDER=gemini (or set OPENAI_API_KEY)."
            )
        return (
            AsyncOpenAI(api_key=gemini_key, base_url=GEMINI_BASE_URL),
            GEMINI_MODEL_NAME,
        )

    raise RuntimeError("Unsupported AI_PROVIDER. Use 'openai', 'gemini', or 'llama'.")


def _get_client_and_model() -> tuple[AsyncOpenAI, str]:
    global _client, _model_name
    if _client is None or _model_name is None:
        _client, _model_name = _build_client_and_model()
    return _client, _model_name


def get_ai_health() -> dict[str, str | bool]:
    if AI_PROVIDER == "llama":
        llama_config = load_llama_config()
        configured = llama_config is not None
        model = llama_config.model if llama_config else os.getenv("LLAMA_MODEL", DEFAULT_LLAMA_MODEL)
        base_url = (
            llama_config.base_url
            if llama_config
            else os.getenv("LLAMA_BASE_URL", DEFAULT_LLAMA_BASE_URL)
        )
        return {
            "status": "ok" if configured else "misconfigured",
            "provider": "llama",
            "model": model,
            "base_url": base_url,
            "configured": configured,
        }

    if AI_PROVIDER == "openai":
        configured = bool(os.getenv("OPENAI_API_KEY"))
        return {
            "status": "ok" if configured else "misconfigured",
            "provider": "openai",
            "model": OPENAI_MODEL_NAME,
            "base_url": OPENAI_BASE_URL or OPENAI_DEFAULT_BASE_URL,
            "configured": configured,
        }

    if AI_PROVIDER == "gemini":
        configured = bool(os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY"))
        return {
            "status": "ok" if configured else "misconfigured",
            "provider": "gemini",
            "model": GEMINI_MODEL_NAME,
            "base_url": GEMINI_BASE_URL,
            "configured": configured,
        }

    return {
        "status": "misconfigured",
        "provider": AI_PROVIDER,
        "model": "",
        "base_url": "",
        "configured": False,
    }


def _with_system_prompt(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    if messages and messages[0]["role"] == "system" and messages[0]["content"] == SYSTEM_PROMPT:
        return messages
    return [{"role": "system", "content": SYSTEM_PROMPT}, *messages]


async def generate_assistant_reply(messages: list[dict[str, str]]) -> str:
    client, model_name = _get_client_and_model()
    response = await client.chat.completions.create(
        model=model_name,
        messages=_with_system_prompt(messages),
    )
    content = response.choices[0].message.content
    return content if content is not None else ""


async def stream_assistant_reply(
    messages: list[dict[str, str]],
) -> AsyncGenerator[str, None]:
    client, model_name = _get_client_and_model()
    stream = await client.chat.completions.create(
        model=model_name,
        messages=_with_system_prompt(messages),
        stream=True,
    )

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
