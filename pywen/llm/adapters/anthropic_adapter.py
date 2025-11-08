from __future__ import annotations
from typing import List, Dict, AsyncGenerator, Generator, Any
from dataclasses import dataclass

@dataclass
class AnthropicAdapter:
    cfg: Any
    def __post_init__(self):
        import anthropic
        self._client = anthropic.Anthropic(api_key=self.cfg.api_key)
        self._aclient = anthropic.AsyncAnthropic(api_key=self.cfg.api_key)

    def _to_anthropic(self, messages: List[Dict[str, str]]):
        system = ""
        content: List[Dict[str, str]] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                system += (m["content"] + "\n")
            elif role in ("user", "assistant"):
                content.append({"role": role, "content": m["content"]})
        system = system.strip()
        return system, content

    def chat(self, messages: List[Dict[str, str]], **params) -> str:
        system, msg = self._to_anthropic(messages)
        kwargs = {
            "model": params.get("model", "claude-3-5-sonnet-20241022"),
            "max_tokens": params.get("max_tokens", 1024),
            "messages": msg
        }
        if system:
            kwargs["system"] = system

        resp = self._client.messages.create(**kwargs)
        out = []
        for blk in getattr(resp, "content", []) or []:
            if getattr(blk, "type", None) == "text":
                out.append(getattr(blk, "text", ""))
        return "".join(out)

    async def achat(self, messages: List[Dict[str, str]], **params) -> str:
        system, msg = self._to_anthropic(messages)
        kwargs = {
            "model": params.get("model", "claude-3-5-sonnet-20241022"),
            "max_tokens": params.get("max_tokens", 1024),
            "messages": msg
        }
        if system:
            kwargs["system"] = system

        resp = await self._aclient.messages.create(**kwargs)
        out = []
        for blk in getattr(resp, "content", []) or []:
            if getattr(blk, "type", None) == "text":
                out.append(getattr(blk, "text", ""))
        return "".join(out)

    def stream(self, messages: List[Dict[str, str]], **params) -> Generator[str, None, None]:
        system, msg = self._to_anthropic(messages)
        kwargs = {
            "model": params.get("model", "claude-3-5-sonnet-20241022"),
            "max_tokens": params.get("max_tokens", 1024),
            "messages": msg
        }
        if system:
            kwargs["system"] = system

        with self._client.messages.stream(**kwargs) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if getattr(delta, "type", None) == "text_delta":
                        txt = getattr(delta, "text", "")
                        if txt:
                            yield txt
                elif event.type == "message_stop":
                    break

    async def astream(self, messages: List[Dict[str, str]], **params) -> AsyncGenerator[str, None]:
        system, msg = self._to_anthropic(messages)
        kwargs = {
            "model": params.get("model", "claude-3-5-sonnet-20241022"),
            "max_tokens": params.get("max_tokens", 1024),
            "messages": msg
        }
        if system:
            kwargs["system"] = system

        async with self._aclient.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if getattr(delta, "type", None) == "text_delta":
                        txt = getattr(delta, "text", "")
                        if txt:
                            yield txt
                elif event.type == "message_stop":
                    break
