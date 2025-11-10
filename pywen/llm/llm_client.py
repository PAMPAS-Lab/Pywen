from __future__ import annotations
import asyncio, time
from typing import Generator,AsyncGenerator,Dict, cast, List, Optional, Protocol,Any
from dataclasses import dataclass
from .adapters.openai_adapter import OpenAIAdapter
from .adapters.anthropic_adapter import AnthropicAdapter
from .adapters.adapter_common import ResponseEvent
from pywen.utils.llm_basics import LLMMessage, LLMResponse

class ProviderAdapter(Protocol):
    def generate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse: ...
    def stream_response(self, messages: List[Dict[str, str]], **params) -> Generator[ResponseEvent, None, None]: ...
    async def agenerate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse: ...
    async def astream_response(self, messages: List[Dict[str, str]], **params) -> AsyncGenerator[ResponseEvent, None]: ...

@dataclass
class LLMConfig():
    # TODO.config重构完成这里需要采用config中的定义
    provider: str = "compatible"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = "gpt-5-codex"
    timeout: float = 60.0
    retry: int = 2
    wire_api: str = "auto"
    use_bearer_auth: bool = False  # 是否使用 Bearer token 认证（用于第三方 Anthropic 兼容服务）

class LLMClient:
    def __init__(self, cfg: Optional[LLMConfig] = None):
        self.cfg = cfg or LLMConfig()
        self._adapter: ProviderAdapter = self._build_adapter(self.cfg)

    @staticmethod
    def _build_adapter(cfg: LLMConfig) -> ProviderAdapter:
        if cfg.provider in ("openai", "compatible"):
            impl = OpenAIAdapter(
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                default_model=cfg.model,
                wire_api=cfg.wire_api,
            )
            return cast(ProviderAdapter, impl)
        elif cfg.provider == "anthropic":
            # 如果模型名不是 claude 开头，说明是第三方服务，使用 Bearer 认证
            use_bearer = False
            if not use_bearer and cfg.model and not cfg.model.lower().startswith("claude"):
                use_bearer = True

            impl = AnthropicAdapter(
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                default_model=cfg.model,
                use_bearer_auth=use_bearer,
            )
            return cast(ProviderAdapter, impl)
        raise ValueError(f"Unknown provider: {cfg.provider}")

    def generate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse:
        return LLMResponse("")

    def stream_response(self, messages: List[Dict[str, str]], **params) -> Generator[ResponseEvent, None, None]: 
        pass

    async def agenerate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse:
        pass

    async def astream_response(self, messages: List[Dict[str, str]], **params) -> AsyncGenerator[ResponseEvent, None]: 
        # 让类型检查器开心
        stream = cast(AsyncGenerator[ResponseEvent, None], self._adapter.astream_response(messages, **params))
        async for ch in stream:
            yield ch

