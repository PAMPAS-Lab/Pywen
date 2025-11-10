from __future__ import annotations
from typing import AsyncGenerator, Dict, Generator, List, Any, Optional
from anthropic import Anthropic, AsyncAnthropic
from pywen.utils.llm_basics import LLMResponse
from .adapter_common import ResponseEvent

def _to_anthropic_messages(messages: List[Dict[str, Any]]):
    """转换消息为 Anthropic 原生格式"""
    system = ""
    content: List[Dict[str, Any]] = []

    for m in messages:
        role = m.get("role", "user")
        msg_content = m.get("content", "")

        if role == "system":
            system += (msg_content + "\n")

        elif role == "user":
            content.append({"role": "user", "content": msg_content})

        elif role == "assistant":
            tool_calls = m.get("tool_calls")
            if tool_calls:
                assistant_content = []
                if msg_content:
                    assistant_content.append({"type": "text", "text": msg_content})
                for tc in tool_calls:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": tc.get("call_id", ""),
                        "name": tc.get("name", ""),
                        "input": tc.get("arguments", {})
                    })
                content.append({"role": "assistant", "content": assistant_content})
            else:
                content.append({"role": "assistant", "content": msg_content})

        elif role == "tool":
            tool_call_id = m.get("tool_call_id", "")
            tool_result_content = [{
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": msg_content
            }]
            content.append({"role": "user", "content": tool_result_content})

    system = system.strip()
    return system, content

class AnthropicAdapter():
    """Anthropic adapter，使用 messages API"""

    def __init__(
        self,
        *,
        api_key: Optional[str],
        base_url: Optional[str],
        default_model: str,
        use_bearer_auth: bool = False,  # 是否使用 Bearer token 认证
    ):
        # 根据第三方服务的要求选择认证方式
        if use_bearer_auth and api_key:
            headers = {"Authorization": f"Bearer {api_key}"}
            self._sync = Anthropic(api_key=api_key, base_url=base_url, default_headers=headers)
            self._async = AsyncAnthropic(api_key=api_key, base_url=base_url, default_headers=headers)
        else:
            # 默认使用 Anthropic 原生的 x-api-key 认证
            self._sync = Anthropic(api_key=api_key, base_url=base_url)
            self._async = AsyncAnthropic(api_key=api_key, base_url=base_url)
        self._default_model = default_model

    def _build_kwargs(self, messages, model, params):
        """构建 API 调用参数"""
        system, msg = _to_anthropic_messages(messages)
        kwargs = {
            "model": model,
            "max_tokens": params.get("max_tokens", 4096),
            "messages": msg,
            **{k: v for k, v in params.items() if k not in ("model", "max_tokens", "api")}
        }
        if system:
            kwargs["system"] = system
        return kwargs
    # 同步非流式
    def generate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse:
        model = params.get("model", self._default_model)
        kwargs = self._build_kwargs(messages, model, params)
        resp = self._sync.messages.create(**kwargs)
        text = resp.content[0].text if resp.content else ""
        return LLMResponse(text)

    # 同步流式 - Native 格式
    def stream_response(self, messages: List[Dict[str, str]], **params) -> Generator[ResponseEvent, None, None]:
        model = params.get("model", self._default_model)
        kwargs = self._build_kwargs(messages, model, params)

        with self._sync.messages.stream(**kwargs) as stream:
            for event in stream:
                evt = self._process_native_event(event)
                if evt:
                    yield evt
                if event.type == "message_stop":
                    break
    # 异步非流式
    async def agenerate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse:
        model = params.get("model", self._default_model)
        kwargs = self._build_kwargs(messages, model, params)
        resp = await self._async.messages.create(**kwargs)
        text = resp.content[0].text if resp.content else ""
        return LLMResponse(text)

    # 异步流式
    async def astream_response(self, messages: List[Dict[str, Any]], **params) -> AsyncGenerator[ResponseEvent, None]:
        model = params.get("model", self._default_model)
        kwargs = self._build_kwargs(messages, model, params)

        async with self._async.messages.stream(**kwargs) as stream:
            async for event in stream:
                evt = self._process_native_event(event)
                if evt:
                    yield evt
                if event.type == "message_stop":
                    break

    def _process_native_event(self, event) -> Optional[ResponseEvent]:
        if event.type == "message_start":
            message_id = getattr(event.message, "id", "")
            return ResponseEvent.message_start({"message_id": message_id})

        elif event.type == "content_block_start":
            block = getattr(event, "content_block", None)
            if block:
                block_type = getattr(block, "type", None)
                if block_type == "tool_use":
                    call_id = getattr(block, "id", "")
                    name = getattr(block, "name", "")
                    return ResponseEvent.content_block_start({"call_id": call_id, "name": name, "block_type": block_type})
                else:
                    return ResponseEvent.content_block_start({"block_type": block_type})

        elif event.type == "content_block_delta":
            delta = event.delta
            delta_type = getattr(delta, "type", None)
            if delta_type == "text_delta":
                text = getattr(delta, "text", "")
                if text:
                    return ResponseEvent.text_delta(text)
            elif delta_type == "input_json_delta":
                partial_json = getattr(delta, "partial_json", "")
                if partial_json:
                    return ResponseEvent.tool_call_delta_json(partial_json)

        elif event.type == "content_block_stop":
            return ResponseEvent.content_block_stop({})

        elif event.type == "message_delta":
            delta = getattr(event, "delta", None)
            usage = getattr(event, "usage", None)

            data = {}
            if delta:
                stop_reason = getattr(delta, "stop_reason", None)
                if stop_reason:
                    data["stop_reason"] = stop_reason
            if usage:
                # usage 包含最终的 token 统计
                # 提取所有可能的字段（Anthropic 原生 + 第三方兼容服务可能返回的字段）
                usage_dict = {
                    "input_tokens": getattr(usage, "input_tokens", 0),
                    "output_tokens": getattr(usage, "output_tokens", 0)
                }

                data["usage"] = usage_dict
            if data:
                return ResponseEvent.message_delta(data)

        elif event.type == "message_stop":
            return ResponseEvent.completed({})

        return None

  

