from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from mcpdrift.providers.anthropic_provider import AnthropicProvider
from mcpdrift.providers.base import LLMProvider


ENV_FILE_PATH = Path(__file__).resolve().parents[2] / ".env"


def get_provider(provider_name: str, model: str) -> LLMProvider:
    normalized = provider_name.strip().lower()

    if normalized == "anthropic":
        api_key = _required_api_key("ANTHROPIC_API_KEY", provider_name)
        return AnthropicProvider(api_key=api_key, model=model)

    if normalized == "together":
        from mcpdrift.providers.openai_compat_provider import OpenAICompatProvider

        api_key = _required_api_key("TOGETHER_API_KEY", provider_name)
        return OpenAICompatProvider(
            base_url="https://api.together.xyz/v1",
            api_key=api_key,
            model=model,
        )

    if normalized == "deepseek":
        from mcpdrift.providers.openai_compat_provider import OpenAICompatProvider

        api_key = _required_api_key("DEEPSEEK_API_KEY", provider_name)
        return OpenAICompatProvider(
            base_url="https://api.deepseek.com",
            api_key=api_key,
            model=model,
        )

    raise ValueError(
        "Unsupported provider {!r}. Expected one of: anthropic, together, deepseek.".format(
            provider_name
        )
    )


def _required_api_key(env_var: str, provider_name: str) -> str:
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)
    api_key = os.environ.get(env_var, "").strip()
    if api_key:
        return api_key

    raise ValueError(
        f"Missing API key for provider '{provider_name}'. Set {env_var} in the environment before running MCPDrift."
    )