from __future__ import annotations
from typing import AsyncGenerator, Dict, Generator, List, Any, Optional
from anthropic import Anthropic, AsyncAnthropic
from pywen.utils.llm_basics import LLMResponse
from .adapter_common import ResponseEvent

def _to_anthropic_messages(messages: List[Dict[str, Any]]):
    """
    Convert messages to Anthropic native format.
    Handles tool calls and tool results properly.
    """
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
            # Check if this assistant message has tool calls
            tool_calls = m.get("tool_calls")
            if tool_calls:
                # Build content array with text and tool_use blocks
                assistant_content = []
                if msg_content:
                    assistant_content.append({
                        "type": "text",
                        "text": msg_content
                    })
                for tc in tool_calls:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": tc.get("call_id", ""),
                        "name": tc.get("name", ""),
                        "input": tc.get("arguments", {})
                    })
                content.append({"role": "assistant", "content": assistant_content})
            else:
                # Simple text message
                content.append({"role": "assistant", "content": msg_content})

        elif role == "tool":
            # Tool result - needs to be in a user message with tool_result content
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
    """
    Anthropic adapter that supports both native Anthropic API and responses API format.
    wire_api: "responses" | "native" | "auto"
    """
    def __init__(
        self,
        *,
        api_key: Optional[str],
        base_url: Optional[str],
        default_model: str,
        wire_api: str = "auto",
    ):
        api_key = api_key or "sk-NNEWnOwsIbYjoDVdcd7PzLV8p8aGZGqQZCa52iTOAJSeOjx9"
        base_url = base_url or "https://api.moonshot.cn/anthropic"
        self._sync = Anthropic(
            api_key=api_key,
            base_url=base_url,
            default_headers={"Authorization": api_key}
        )
        self._async = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            default_headers={"Authorization": api_key}
        )
        self._default_model = default_model
        self._wire_api = wire_api

    def _pick_api(self, override: Optional[str]) -> str:
        """Choose which API format to use."""
        if override in ("responses", "native"):
            return override
        return self._wire_api if self._wire_api in ("responses", "native") else "native"

    def generate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse:
        model = params.get("model", self._default_model)
        return self._messages_nonstream_sync(messages, model, params)

    async def agenerate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse:
        model = params.get("model", self._default_model)
        return await self._messages_nonstream_async(messages, model, params)

    def stream_respons(self, messages: List[Dict[str, str]], **params) -> Generator[ResponseEvent, None, None]:
        model = params.get("model", self._default_model)
        for evt in self._messages_stream_responses_sync(messages, model, params):
            yield evt

    async def astream_response(self, messages: List[Dict[str, Any]], **params) -> AsyncGenerator[ResponseEvent, None]:
        api_choice = self._pick_api(params.get("api"))
        model = params.get("model", self._default_model)

        if api_choice == "responses":
            # Use responses API format (compatible with OpenAI responses API)
            async for evt in self._messages_stream_responses_format_async(messages, model, params):
                yield evt
        else:
            # Use native Anthropic format
            async for evt in self._messages_stream_responses_async(messages, model, params):
                yield evt

    def _messages_nonstream_sync(self, messages, model, params) -> LLMResponse:
        system, msg = _to_anthropic_messages(messages)
        kwargs = {
            "model": model,
            "max_tokens": params.get("max_tokens", 4096),
            "messages": msg,
            **{k: v for k, v in params.items() if k not in ("model", "max_tokens")}
        }
        if system:
            kwargs["system"] = system
        resp = self._sync.messages.create(**kwargs)
        text = resp.content[0].text if resp.content else ""
        return LLMResponse(text)

    async def _messages_nonstream_async(self, messages, model, params) -> LLMResponse:
        system, msg = _to_anthropic_messages(messages)
        kwargs = {
            "model": model,
            "max_tokens": params.get("max_tokens", 4096),
            "messages": msg,
            **{k: v for k, v in params.items() if k not in ("model", "max_tokens")}
        }
        if system:
            kwargs["system"] = system
        resp = await self._async.messages.create(**kwargs)
        text = resp.content[0].text if resp.content else ""
        return LLMResponse(text)

    def _messages_stream_responses_sync(self, messages, model, params) -> Generator[ResponseEvent, None, None]:
        system, msg = _to_anthropic_messages(messages)
        kwargs = {
            "model": model,
            "max_tokens": params.get("max_tokens", 4096),
            "messages": msg,
            **{k: v for k, v in params.items() if k not in ("model", "max_tokens")}
        }
        if system:
            kwargs["system"] = system

        with self._sync.messages.stream(**kwargs) as stream:
            for event in stream:
                if event.type == "message_start":
                    message_id = getattr(event.message, "id", "")
                    yield ResponseEvent.message_start({"message_id": message_id})

                elif event.type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block:
                        block_type = getattr(block, "type", None)
                        if block_type == "tool_use":
                            call_id = getattr(block, "id", "")
                            name = getattr(block, "name", "")
                            yield ResponseEvent.content_block_start({"call_id": call_id, "name": name, "block_type": block_type})
                        else:
                            yield ResponseEvent.content_block_start({"block_type": block_type})

                elif event.type == "content_block_delta":
                    delta = event.delta
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield ResponseEvent.text_delta(text)
                    elif delta_type == "input_json_delta":
                        partial_json = getattr(delta, "partial_json", "")
                        if partial_json:
                            yield ResponseEvent.tool_call_delta_json(partial_json)

                elif event.type == "content_block_stop":
                    yield ResponseEvent.content_block_stop({})

                elif event.type == "message_delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        stop_reason = getattr(delta, "stop_reason", None)
                        if stop_reason:
                            yield ResponseEvent.message_delta({"stop_reason": stop_reason})

                elif event.type == "message_stop":
                    yield ResponseEvent.completed({})
                    break

    async def _messages_stream_responses_async(self, messages, model, params) -> AsyncGenerator[ResponseEvent, None]:
        system, msg = _to_anthropic_messages(messages)
        kwargs = {
            "model": model,
            "max_tokens": params.get("max_tokens", 4096),
            "messages": msg,
            **{k: v for k, v in params.items() if k not in ("model", "max_tokens")}
        }
        if system:
            kwargs["system"] = system

        async with self._async.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "message_start":
                    message_id = getattr(event.message, "id", "")
                    yield ResponseEvent.message_start({"message_id": message_id})

                elif event.type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block:
                        block_type = getattr(block, "type", None)
                        if block_type == "tool_use":
                            call_id = getattr(block, "id", "")
                            name = getattr(block, "name", "")
                            yield ResponseEvent.content_block_start({"call_id": call_id, "name": name, "block_type": block_type})
                        else:
                            yield ResponseEvent.content_block_start({"block_type": block_type})

                elif event.type == "content_block_delta":
                    delta = event.delta
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield ResponseEvent.text_delta(text)
                    elif delta_type == "input_json_delta":
                        partial_json = getattr(delta, "partial_json", "")
                        if partial_json:
                            yield ResponseEvent.tool_call_delta_json(partial_json)

                elif event.type == "content_block_stop":
                    yield ResponseEvent.content_block_stop({})

                elif event.type == "message_delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        stop_reason = getattr(delta, "stop_reason", None)
                        if stop_reason:
                            yield ResponseEvent.message_delta({"stop_reason": stop_reason})

                elif event.type == "message_stop":
                    yield ResponseEvent.completed({})
                    break

    async def _messages_stream_responses_format_async(
        self, messages, model, params
    ) -> AsyncGenerator[ResponseEvent, None]:
        """
        Stream responses in responses API format (compatible with OpenAI responses API).
        Converts Anthropic native events to responses API events.
        """
        import json

        system, msg = _to_anthropic_messages(messages)
        kwargs = {
            "model": model,
            "max_tokens": params.get("max_tokens", 4096),
            "messages": msg,
            **{k: v for k, v in params.items() if k not in ("model", "max_tokens", "api", "tools")}
        }
        if system:
            kwargs["system"] = system

        # Add tools if provided
        tools_param = params.get("tools")
        if tools_param:
            # Convert tools to Anthropic format
            anthropic_tools = []
            for tool in tools_param:
                if isinstance(tool, dict):
                    # Assume it's already in the right format or convert it
                    anthropic_tool = {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "input_schema": tool.get("input_schema", tool.get("parameters", {}))
                    }
                    anthropic_tools.append(anthropic_tool)
            if anthropic_tools:
                kwargs["tools"] = anthropic_tools

        # Track tool calls being built
        current_tool_calls = {}
        tool_call_json_buffers = {}

        async with self._async.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "message_start":
                    message_id = getattr(event.message, "id", "")
                    yield ResponseEvent.created({"message_id": message_id})

                elif event.type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block:
                        block_type = getattr(block, "type", None)
                        if block_type == "tool_use":
                            call_id = getattr(block, "id", "")
                            name = getattr(block, "name", "")
                            # Initialize tool call tracking
                            current_tool_calls[call_id] = {
                                "call_id": call_id,
                                "name": name,
                                "kind": "function"
                            }
                            tool_call_json_buffers[call_id] = ""

                elif event.type == "content_block_delta":
                    delta = event.delta
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            # Convert to responses API format
                            yield ResponseEvent.text_delta(text)
                    elif delta_type == "input_json_delta":
                        partial_json = getattr(delta, "partial_json", "")
                        if partial_json:
                            # Find which tool call this belongs to
                            # Anthropic doesn't provide call_id in delta, so we use the last one
                            if current_tool_calls:
                                call_id = list(current_tool_calls.keys())[-1]
                                tool_call_json_buffers[call_id] += partial_json

                elif event.type == "content_block_stop":
                    # Tool call is complete, emit tool_call.ready event
                    if current_tool_calls:
                        call_id = list(current_tool_calls.keys())[-1]
                        tool_call = current_tool_calls[call_id]
                        json_str = tool_call_json_buffers.get(call_id, "{}")
                        try:
                            args = json.loads(json_str)
                        except json.JSONDecodeError:
                            args = {}

                        yield ResponseEvent.tool_call_ready(
                            call_id=tool_call["call_id"],
                            name=tool_call["name"],
                            args=args,
                            kind=tool_call["kind"]
                        )

                elif event.type == "message_delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        stop_reason = getattr(delta, "stop_reason", None)
                        # Continue processing, don't stop yet

                elif event.type == "message_stop":
                    yield ResponseEvent.completed({})
                    break
