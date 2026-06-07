from __future__ import annotations

from typing import AsyncGenerator, Dict, Generator, List, Protocol, cast

from pywen.config.config import AgentConfig
from pywen.llm.llm_basics import LLMResponse

from .adapters.anthropic_adapter import AnthropicAdapter
from .adapters.openai_adapter import OpenAIAdapter
from .llm_events import ResponseEvent


class ProviderAdapter(Protocol):
    def generate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse: ...
    def stream_response(self, messages: List[Dict[str, str]], **params) -> Generator[ResponseEvent, None, None]: ...
    async def agenerate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse: ...
    async def astream_response(self, messages: List[Dict[str, str]], **params) -> AsyncGenerator[ResponseEvent, None]: ...

class LLMClient:
    def __init__(self, cfg: AgentConfig) -> None:
        self.cfg = cfg 
        self._adapter: ProviderAdapter = self._build_adapter(self.cfg)

    @staticmethod
    def _build_adapter(cfg: AgentConfig) -> ProviderAdapter:
        if cfg.provider in ("openai", "compatible"):
            impl = OpenAIAdapter(
                api_key=cfg.model.api_key,
                base_url=cfg.model.base_url,
                default_model=cfg.model.model_name or "",
                wire_api=cfg.wire_api or "",
            )
            return cast(ProviderAdapter, impl)
        elif cfg.provider == "anthropic":
            # 如果模型名不是 claude 开头，说明是第三方服务，使用 Bearer 认证
            use_bearer = False
            if not use_bearer and cfg.model and not cfg.model.model_name.lower().startswith("claude"):
                use_bearer = True

            impl = AnthropicAdapter(
                api_key=cfg.model.api_key,
                base_url=cfg.model.base_url,
                default_model=cfg.model.model_name or "",
                use_bearer_auth=use_bearer,
            )
            return cast(ProviderAdapter, impl)
        raise ValueError(f"Unknown provider: {cfg.provider}")

    # 同步，非流式 
    def generate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse:
        return LLMResponse("")

    # 同步，流式 
    def stream_response(self, messages: List[Dict[str, str]], **params) -> Generator[ResponseEvent, None, None]: 
        yield ResponseEvent(type="error", data="")

    # 异步，非流式
    async def agenerate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse:
        return LLMResponse("")

    # 异步，流式
    async def astream_response(self, messages: List[Dict[str, str]], **params) -> AsyncGenerator[ResponseEvent, None]: 
        # 让类型检查器开心
        stream = cast(AsyncGenerator[ResponseEvent, None], self._adapter.astream_response(messages, **params))
        async for ch in stream:
            yield ch
