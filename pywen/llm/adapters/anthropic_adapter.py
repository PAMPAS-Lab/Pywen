from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

from anthropic import Anthropic, AsyncAnthropic

from pywen.llm.llm_basics import LLMResponse
from pywen.llm.llm_events import ResponseEvent


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

        # 用于收集完整的 usage 信息
        input_tokens_from_start = None

        try:
            with self._sync.messages.stream(**kwargs) as stream:
                for event in stream:
                    # 从 message_start 提取 input_tokens（Anthropic API 风格）
                    if event.type == "message_start":
                        message = getattr(event, "message", None)
                        if message:
                            usage = getattr(message, "usage", None)
                            if usage:
                                input_tokens_from_start = getattr(usage, "input_tokens", None)
                    
                    evt = self._process_native_event(event, input_tokens_from_start)
                    if evt:
                        yield evt
                    if event.type == "message_stop":
                        break
        except Exception as e:
            # Anthropic SDK 在出错时会抛出异常，需要转换为 error 事件
            yield ResponseEvent.error(str(e), {"exception_type": type(e).__name__})
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

        # 用于收集完整的 usage 信息
        input_tokens_from_start = None
        
        try:
            async with self._async.messages.stream(**kwargs) as stream:
                async for event in stream:
                    # 从 message_start 提取 input_tokens（Anthropic API 风格）
                    if event.type == "message_start":
                        message = getattr(event, "message", None)
                        if message:
                            usage = getattr(message, "usage", None)
                            if usage:
                                input_tokens_from_start = getattr(usage, "input_tokens", None)
                    
                    evt = self._process_native_event(event, input_tokens_from_start)
                    if evt:
                        yield evt
                    if event.type == "message_stop":
                        break
        except Exception as e:
            # Anthropic SDK 在出错时会抛出异常，需要转换为 error 事件
            yield ResponseEvent.error(str(e), {"exception_type": type(e).__name__})

    def _process_native_event(self, event, input_tokens_from_start: Optional[int] = None) -> Optional[ResponseEvent]:
        """将 Anthropic 原生事件映射到标准 LLM_Events"""

        if event.type == "message_start":
            # message_start -> request.started
            message = getattr(event, "message", None)
            data = {}
            if message:
                message_id = getattr(message, "id", "")
                if message_id:
                    data["response_id"] = message_id
            return ResponseEvent.request_started(data)

        elif event.type == "content_block_start":
            # content_block_start: 记录 tool_use 的 call_id 和 name
            block = getattr(event, "content_block", None)
            if block:
                block_type = getattr(block, "type", None)
                if block_type == "tool_use":
                    # 保存 tool call 信息用于后续的 delta 事件
                    call_id = getattr(block, "id", "")
                    name = getattr(block, "name", "")
                    self._current_tool_call = {"call_id": call_id, "name": name, "arguments": ""}
            return None  # 不产生事件，等待后续内容

        elif event.type == "content_block_delta":
            delta = event.delta
            delta_type = getattr(delta, "type", None)
            if delta_type == "text_delta":
                # text_delta -> assistant.delta
                text = getattr(delta, "text", "")
                if text:
                    return ResponseEvent.assistant_delta(text)
            elif delta_type == "input_json_delta":
                # input_json_delta -> tool_call.delta，同时累积 arguments
                partial_json = getattr(delta, "partial_json", "")
                if partial_json:
                    tool_info = getattr(self, "_current_tool_call", {})
                    # 累积 arguments
                    if hasattr(self, "_current_tool_call"):
                        self._current_tool_call["arguments"] += partial_json
                    return ResponseEvent.tool_call_delta(
                        call_id=tool_info.get("call_id", ""),
                        name=tool_info.get("name"),
                        arguments=partial_json,
                        kind="function"
                    )
            elif delta_type == "thinking_delta":
                # thinking_delta -> reasoning.delta (extended thinking)
                thinking = getattr(delta, "thinking", "")
                if thinking:
                    return ResponseEvent.reasoning_delta(thinking)

        elif event.type == "content_block_stop":
            # content_block_stop: 如果是 tool call，发送 tool_call_ready 事件
            if hasattr(self, "_current_tool_call") and self._current_tool_call:
                import json
                tool_call = self._current_tool_call.copy()
                # 解析累积的 arguments JSON
                try:
                    tool_call["arguments"] = json.loads(tool_call["arguments"]) if tool_call["arguments"] else {}
                except json.JSONDecodeError:
                    tool_call["arguments"] = {}
                delattr(self, "_current_tool_call")
                return ResponseEvent.tool_call_ready(tool_call)
            return None  # 不产生事件

        elif event.type == "message_delta":
            # message_delta: 处理 usage 信息 -> metrics.token_usage
            usage = getattr(event, "usage", None)
            if usage:
                input_tokens = getattr(usage, "input_tokens", None)
                output_tokens = getattr(usage, "output_tokens", None)

                # 如果 message_delta 中没有 input_tokens，使用从 message_start 提取的值
                if input_tokens is None and input_tokens_from_start is not None:
                    input_tokens = input_tokens_from_start

                usage_dict = {
                    "input_tokens": input_tokens if input_tokens else 0,
                    "output_tokens": output_tokens if output_tokens is not None else 0,
                }
                usage_dict["total_tokens"] = usage_dict["input_tokens"] + usage_dict["output_tokens"]
                return ResponseEvent.token_usage(usage_dict)
            return None

        elif event.type == "message_stop":
            return ResponseEvent.response_finished({})

        return None
