from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mcpdrift.providers import factory
from mcpdrift.providers.anthropic_provider import AnthropicProvider
from mcpdrift.providers.factory import MODEL_REGISTRY, _required_api_key
from mcpdrift.providers.openai_compat_provider import OpenAICompatProvider


class _FakeAnthropicBlock:
    def __init__(self, block_type: str, text: str = "", name: str = "", payload: dict[str, Any] | None = None) -> None:
        self.type = block_type
        self.text = text
        self.name = name
        self.input = payload or {}


class _FakeAnthropicResponse:
    def __init__(self) -> None:
        self.content = [
            _FakeAnthropicBlock("text", text="Checking the README."),
            _FakeAnthropicBlock("tool_use", name="file_read", payload={"path": "/data/project/readme.md"}),
        ]

    def model_dump(self) -> dict[str, Any]:
        return {"provider": "anthropic", "id": "resp_123"}


class _FakeAnthropicMessages:
    def create(self, **kwargs: Any) -> _FakeAnthropicResponse:
        return _FakeAnthropicResponse()


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = _FakeAnthropicMessages()


class _FakeOpenAIFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeOpenAIToolCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.function = _FakeOpenAIFunction(name, arguments)


class _FakeOpenAIMessage:
    def __init__(self) -> None:
        self.content = "Running the backup flow."
        self.tool_calls = [
            _FakeOpenAIToolCall(
                "file_write",
                '{"path": "/data/project/report.md", "content": "status"}',
            )
        ]


class _FakeOpenAIChoice:
    def __init__(self) -> None:
        self.message = _FakeOpenAIMessage()


class _FakeOpenAIResponse:
    def __init__(self) -> None:
        self.choices = [_FakeOpenAIChoice()]

    def model_dump(self) -> dict[str, Any]:
        return {"provider": "openai-compatible", "id": "chatcmpl_123"}


class _FakeOpenAICompletions:
    def create(self, **kwargs: Any) -> _FakeOpenAIResponse:
        return _FakeOpenAIResponse()


class _FakeOpenAIChat:
    def __init__(self) -> None:
        self.completions = _FakeOpenAICompletions()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = _FakeOpenAIChat()


def test_anthropic_provider_normalizes_response() -> None:
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider.model = "claude-sonnet-4-6"
    provider.temperature = 0.0
    provider.client = _FakeAnthropicClient()

    response = provider.complete(messages=[{"role": "user", "content": "Read README"}], tools=[])

    assert response.text == "Checking the README."
    assert response.tool_calls == [
        {"tool_name": "file_read", "parameters": {"path": "/data/project/readme.md"}}
    ]
    assert response.raw["provider"] == "anthropic"
    assert response.latency_ms >= 0.0


def test_openai_compat_provider_normalizes_response() -> None:
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
    provider.model = "deepseek-v4-flash"
    provider.base_url = "https://api.deepseek.com"
    provider.client = _FakeOpenAIClient()

    response = provider.complete(messages=[{"role": "user", "content": "Write report"}], tools=[])

    assert response.text == "Running the backup flow."
    assert response.tool_calls == [
        {
            "tool_name": "file_write",
            "parameters": {"path": "/data/project/report.md", "content": "status"},
        }
    ]
    assert response.raw["provider"] == "openai-compatible"
    assert response.latency_ms >= 0.0


def test_required_api_key_loads_from_dotenv(tmp_path: Path, monkeypatch: Any) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("DEEPSEEK_API_KEY=dotenv-secret\n", encoding="utf-8")

    monkeypatch.setattr("mcpdrift.providers.factory.ENV_FILE_PATH", dotenv_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert _required_api_key("DEEPSEEK_API_KEY", "deepseek") == "dotenv-secret"


@pytest.fixture
def _stub_openai(monkeypatch: Any) -> None:
    """Provide a minimal ``openai`` module so provider construction works
    without the real package installed (it is a declared dependency installed
    in CI)."""
    import sys
    import types

    if "openai" in sys.modules:
        return

    module = types.ModuleType("openai")

    class _StubOpenAI:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    module.OpenAI = _StubOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)


@pytest.mark.parametrize("slug", sorted(MODEL_REGISTRY))
def test_factory_create_all_slugs(
    slug: str, tmp_path: Path, monkeypatch: Any, _stub_openai: None
) -> None:
    spec = MODEL_REGISTRY[slug]
    # Isolate from any real .env on disk and provide a dummy key.
    monkeypatch.setattr("mcpdrift.providers.factory.ENV_FILE_PATH", tmp_path / ".env")
    monkeypatch.setenv(spec.env_var, "test-key")

    provider = factory.create(slug)

    assert provider is not None
    if spec.provider == "anthropic":
        assert isinstance(provider, AnthropicProvider)
    else:
        assert isinstance(provider, OpenAICompatProvider)
    assert provider.model == spec.model


def test_factory_create_missing_key_raises(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr("mcpdrift.providers.factory.ENV_FILE_PATH", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY not set. Export it to use gpt-4.1."):
        factory.create("gpt-4.1")


def test_factory_create_skip_missing_returns_none(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr("mcpdrift.providers.factory.ENV_FILE_PATH", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert factory.create("gpt-4.1", skip_missing=True) is None
