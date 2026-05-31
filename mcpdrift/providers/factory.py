from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from mcpdrift.providers.anthropic_provider import AnthropicProvider
from mcpdrift.providers.base import LLMProvider


ENV_FILE_PATH = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class ModelSpec:
    """Static description of a benchmarkable model.

    ``provider`` is the provider *category* (``anthropic``, ``together``,
    ``deepseek``, ``openai`` or ``google``). Everything except ``anthropic``
    speaks the OpenAI-compatible chat-completions API and is served through
    ``OpenAICompatProvider`` with the appropriate ``base_url``.
    """

    slug: str
    model: str
    provider: str
    env_var: str
    display_name: str
    base_url: str | None = None


# Registry of every model the benchmark can run, keyed by stable slug.
# Existing three models first, then the five added in Phase 2.
MODEL_REGISTRY: dict[str, ModelSpec] = {
    "claude-sonnet-4-6": ModelSpec(
        slug="claude-sonnet-4-6",
        model="claude-sonnet-4-6",
        provider="anthropic",
        env_var="ANTHROPIC_API_KEY",
        display_name="Claude 4.6",
    ),
    "llama-3.3-70b": ModelSpec(
        slug="llama-3.3-70b",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        provider="together",
        env_var="TOGETHER_API_KEY",
        display_name="Llama 3.3 70B",
        base_url="https://api.together.xyz/v1",
    ),
    "deepseek-v4-flash": ModelSpec(
        slug="deepseek-v4-flash",
        model="deepseek-v4-flash",
        provider="deepseek",
        env_var="DEEPSEEK_API_KEY",
        display_name="DeepSeek V4 Flash",
        base_url="https://api.deepseek.com",
    ),
    "gpt-4.1": ModelSpec(
        slug="gpt-4.1",
        model="gpt-4.1",
        provider="openai",
        env_var="OPENAI_API_KEY",
        display_name="GPT-4.1",
        base_url="https://api.openai.com/v1",
    ),
    "gemini-2.5-flash": ModelSpec(
        slug="gemini-2.5-flash",
        model="gemini-2.5-flash",
        provider="google",
        env_var="GOOGLE_API_KEY",
        display_name="Gemini 2.5 Flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    "qwen2.5-7b": ModelSpec(
        slug="qwen2.5-7b",
        model="Qwen/Qwen2.5-7B-Instruct-Turbo",
        provider="together",
        env_var="TOGETHER_API_KEY",
        display_name="Qwen2.5 7B",
        base_url="https://api.together.xyz/v1",
    ),
    "llama-3-8b": ModelSpec(
        slug="llama-3-8b",
        model="meta-llama/Meta-Llama-3-8B-Instruct-Lite",
        provider="together",
        env_var="TOGETHER_API_KEY",
        display_name="Llama 3 8B",
        base_url="https://api.together.xyz/v1",
    ),
    "qwen3-235b": ModelSpec(
        slug="qwen3-235b",
        model="Qwen/Qwen3-235B-A22B-Instruct-2507-tput",
        provider="together",
        env_var="TOGETHER_API_KEY",
        display_name="Qwen3 235B",
        base_url="https://api.together.xyz/v1",
    ),
}


def get_model_spec(slug: str) -> ModelSpec:
    spec = MODEL_REGISTRY.get(slug)
    if spec is None:
        known = ", ".join(sorted(MODEL_REGISTRY))
        raise ValueError(f"Unknown model slug {slug!r}. Known models: {known}.")
    return spec


def has_api_key(slug: str) -> bool:
    """Return ``True`` when the API key for ``slug`` is available."""
    spec = get_model_spec(slug)
    return bool(_load_api_key(spec.env_var))


def create(slug: str, skip_missing: bool = False) -> LLMProvider | None:
    """Instantiate the provider for ``slug``.

    When the required API key is missing, raise ``ValueError`` unless
    ``skip_missing`` is set, in which case ``None`` is returned so callers can
    gracefully skip the model.
    """
    spec = get_model_spec(slug)
    api_key = _load_api_key(spec.env_var)
    if not api_key:
        if skip_missing:
            return None
        raise ValueError(f"{spec.env_var} not set. Export it to use {slug}.")

    if spec.provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=spec.model)

    from mcpdrift.providers.openai_compat_provider import OpenAICompatProvider

    if spec.base_url is None:
        raise ValueError(f"Model {slug!r} requires a base_url for provider {spec.provider!r}.")
    return OpenAICompatProvider(
        base_url=spec.base_url,
        api_key=api_key,
        model=spec.model,
        supports_seed=spec.provider != "google",
    )


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

    if normalized == "openai":
        from mcpdrift.providers.openai_compat_provider import OpenAICompatProvider

        api_key = _required_api_key("OPENAI_API_KEY", provider_name)
        return OpenAICompatProvider(
            base_url="https://api.openai.com/v1",
            api_key=api_key,
            model=model,
        )

    if normalized == "google":
        from mcpdrift.providers.openai_compat_provider import OpenAICompatProvider

        api_key = _required_api_key("GOOGLE_API_KEY", provider_name)
        return OpenAICompatProvider(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=api_key,
            model=model,
        )

    raise ValueError(
        "Unsupported provider {!r}. Expected one of: anthropic, together, deepseek, openai, google.".format(
            provider_name
        )
    )


def _load_api_key(env_var: str) -> str:
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)
    return os.environ.get(env_var, "").strip()


def _required_api_key(env_var: str, provider_name: str) -> str:
    api_key = _load_api_key(env_var)
    if api_key:
        return api_key

    raise ValueError(
        f"Missing API key for provider '{provider_name}'. Set {env_var} in the environment before running MCPDrift."
    )