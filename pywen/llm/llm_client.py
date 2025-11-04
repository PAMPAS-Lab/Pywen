from __future__ import annotations
import asyncio, time
from typing import Generator,AsyncGenerator,Dict, cast, List, Optional, Protocol,Any
from dataclasses import dataclass
from .adapters.openai_adapter import OpenAIAdapter
from .adapters.adapter_common import ResponseEvent
from pywen.utils.llm_basics import LLMMessage 
# from .adapters.anthropic_adapter import AnthropicAdapter

class ProviderAdapter(Protocol):
    def chat(self, messages: List[Dict[str, str]], **params) -> str: ...
    async def achat(self, messages: List[Dict[str, str]], **params) -> str: ...
    def stream(self, messages: List[Dict[str, str]], **params) -> Generator[str, None, None]: ...
    async def astream(self, messages: List[Dict[str, str]], **params) -> AsyncGenerator[ResponseEvent, None]: ...

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
                wire_api =cfg.wire_api,
            )
            return cast(ProviderAdapter, impl)
        # elif cfg.provider == "anthropic":
        #     return AnthropicAdapter(cfg)
        raise ValueError(f"Unknown provider: {cfg.provider}")

    def chat(self, messages: List[Dict[str, str]], **params) -> str:
        last_e = None
        for attempt in range(self.cfg.retry + 1):
            try:
                return self._adapter.chat(messages, **params)
            except Exception as e:
                last_e = e
                if attempt >= self.cfg.retry:
                    raise
                time.sleep(0.5 * (2 ** attempt))
        if last_e:
            raise last_e
        return ""

    async def achat(self, messages: List[Dict[str, str]], **params) -> str:
        last_e = None
        for attempt in range(self.cfg.retry + 1):
            try:
                return await asyncio.wait_for(
                    self._adapter.achat(messages, **params),
                    timeout=self.cfg.timeout
                )
            except Exception as e:
                last_e = e
                if attempt >= self.cfg.retry:
                    raise
                await asyncio.sleep(0.5 * (2 ** attempt))
        if last_e:
            raise last_e
        return ""

    def stream(self, messages: List[Dict[str, str]], **params) -> Generator[str, None, None]:
        yield from self._adapter.stream(messages, **params)

    async def astream(self, messages: List[Dict[str, str]], **params) -> AsyncGenerator[ResponseEvent, None]:
        # 让类型检查器开心
        stream = cast(AsyncGenerator[ResponseEvent, None], self._adapter.astream(messages, **params))
        async for ch in stream:
            yield ch

