from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, cast

from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletionMessageParam

from pywen.llm.llm_basics import LLMResponse
from pywen.llm.llm_events import ResponseEvent


def _to_chat_messages(messages: List[Dict[str, Any]]) -> List[ChatCompletionMessageParam]:
    converted: List[ChatCompletionMessageParam] = []
    for msg in messages:
        role = msg.get("role")
        item: Dict[str, Any] = {"role": role}
        if "content" in msg:
            item["content"] = msg["content"]
        if role == "assistant" and "tool_calls" in msg:
            item["tool_calls"] = msg["tool_calls"]
        if role == "tool" and "tool_call_id" in msg:
            item["tool_call_id"] = msg["tool_call_id"]
        if "name" in msg:
            item["name"] = msg["name"]
        converted.append(cast(ChatCompletionMessageParam, item))

    return converted

class OpenAIAdapter():
    """
    同时支持 Responses API 与 Chat Completions API。
    wire_api: "responses" | "chat" | "auto"
    """
    def __init__(
        self,
        *,
        api_key: Optional[str],
        base_url: Optional[str],
        default_model: str,
        wire_api: str = "auto",
    ):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self._sync = OpenAI(api_key=api_key, base_url=base_url)
        self._async = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._default_model = default_model
        self._wire_api = wire_api

    #同步非流式,未实现
    def generate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse: 
        return LLMResponse("")

    #异步非流式,未实现
    async def agenerate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse: 
        return LLMResponse("")

    #同步流式,未实现
    def stream_respons(self, messages: List[Dict[str, str]], **params) -> Generator[ResponseEvent, None, None]:
        yield ResponseEvent.error("error")

    #异步流式,实现
    async def astream_response(self, messages: List[Dict[str, Any]], **params) -> AsyncGenerator[ResponseEvent, None]:
        api_choice = self._pick_api(params.get("api"))
        model = params.get("model", self._default_model)
        if api_choice == "chat":
            async for evt in self._chat_stream_responses_async(messages, model, params):
                yield evt
        elif api_choice == "responses":
            async for evt in self._responses_stream_responses_async(messages, model, params):
                yield evt

    def _pick_api(self, override: Optional[str]) -> str:
        if override in ("responses", "chat"):
            return override
        return self._wire_api

    # responses 异步 流式
    async def _responses_stream_responses_async(self, messages, model, params) -> AsyncGenerator[ResponseEvent, None]:
        stream = await self._async.responses.create(
            model=model,
            input= messages,
            stream=True,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        async for event in stream:
            if event.type == "response.created":
                payload = {"response_id": event.response.id}
                yield ResponseEvent.request_started(payload)

            elif event.type == "response.failed":
                error_msg = getattr(event, "error", "error")
                yield ResponseEvent.error(error_msg)

            elif event.type == "response.output_item.done":
                yield ResponseEvent.tool_call_ready(event.item)

            elif event.type == "response.output_text.delta":
                yield ResponseEvent.assistant_delta(event.delta)

            elif event.type == "response.reasoning_text.delta":
                yield ResponseEvent.reasoning_delta(event.delta)

            elif event.type == "response.reasoning_summary_text.delta":
                yield ResponseEvent.reasoning_finished(event.delta)

            elif event.type == "response.content_part.done" or \
                event.type == "response.function_call_arguments.delta" or \
                event.type == "response.function_call_arguments.done" or \
                event.type == "response.custom_tool_call_input.delta" or \
                event.type == "response.custom_tool_call_input.done" or \
                event.type == "response.in_progress" or \
                event.type == "response.output_text.done":
                continue

            elif event.type == "response.output_item.added":
                item = event.item 
                if item.type == "web_search_call":
                    call_id = item.id 
                    yield ResponseEvent.web_search_begin(call_id)

            elif event.type == "response.completed":
                resp_usage = event.response.usage
                usage = {
                            "input_tokens": resp_usage.input_tokens if resp_usage else 0, 
                            "output_tokens": resp_usage.output_tokens if resp_usage else 0, 
                            "token_usage": resp_usage.total_tokens if resp_usage else 0,
                         }
                yield ResponseEvent.token_usage(usage)
                yield ResponseEvent.response_finished(event.response)
                break

            elif event.type == "error":
                yield ResponseEvent.error(getattr(event, "error", "") or "error")
                break

    #chat 异步 流式
    async def _chat_stream_responses_async(self, messages, model, params) -> AsyncGenerator[ResponseEvent, None]:
        chat_msgs = _to_chat_messages(messages)
        stream = await self._async.chat.completions.create(
            model=model,
            messages=chat_msgs,
            stream=True,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        yield ResponseEvent.request_started({})
        tool_calls: dict[int, dict] = {}
        text_buffer: str = ""
        async for chunk in stream:
            delta = chunk.choices[0].delta
            for tc_delta in delta.tool_calls or []:
                idx = tc_delta.index
                data = tool_calls.setdefault(
                    idx, 
                    {"call_id": "", "name": "", "arguments": "", "type": ""}
                )
                data["type"] = tc_delta.type or data["type"]
                data["call_id"] = tc_delta.id or data["call_id"]
                if tc_delta.function:
                    data["name"] = tc_delta.function.name or data["name"]
                    data["arguments"] += tc_delta.function.arguments  or ""
                    yield ResponseEvent.tool_call_delta(data["call_id"], data["name"], tc_delta.function.arguments  or "", data["type"])

            if delta.content:
                text_buffer += delta.content
                yield ResponseEvent.assistant_delta(delta.content or "")

            finish_reason = chunk.choices[0].finish_reason
            payload = {"content": text_buffer, "finish_reason": finish_reason, "usage": chunk.usage or {}}
            if finish_reason == "tool_calls":
                # tool_call中包含call_id, name, arguments, type
                for tc in tool_calls.values():
                    try:
                        tc["arguments"] = json.loads(tc["arguments"])
                    except Exception:
                        tc["arguments"] = {}
                payload["tool_calls"] = list(tool_calls.values())
                yield ResponseEvent.tool_call_ready(list(tool_calls.values()))
                usage = {
                            "input_tokens": 0, 
                            "output_tokens": 0, 
                            "total_tokens": chunk.usage.total_tokens if chunk.usage and chunk.usage.total_tokens else 0,
                         }
                yield ResponseEvent.token_usage(usage)
            if finish_reason is not None:
                # 包含tool_calls信息, tool_call中包含call_id, name, arguments, type
                yield ResponseEvent.response_finished(payload)
