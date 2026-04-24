import os

from pydantic import BaseModel, Field


DEFAULT_LLAMA_BASE_URL = "https://api.llmapi.ai/v1"
DEFAULT_LLAMA_MODEL = "meta-llama/llama-3.1-8b-instruct"


class LlamaConfig(BaseModel):
    api_key: str = Field(min_length=1)
    base_url: str = DEFAULT_LLAMA_BASE_URL
    model: str = DEFAULT_LLAMA_MODEL


def load_llama_config() -> LlamaConfig | None:
    api_key = os.getenv("LLAMA_API_KEY")
    if not api_key:
        return None

    return LlamaConfig(
        api_key=api_key,
        base_url=os.getenv("LLAMA_BASE_URL", DEFAULT_LLAMA_BASE_URL),
        model=os.getenv("LLAMA_MODEL", DEFAULT_LLAMA_MODEL),
    )
