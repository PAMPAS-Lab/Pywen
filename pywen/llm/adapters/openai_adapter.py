from __future__ import annotations
import os,json
from typing import AsyncGenerator, Dict, Generator, List, Any, Optional, cast
from openai import OpenAI, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.responses import ResponseInputParam
from pywen.utils.llm_basics import LLMResponse
from .adapter_common import ResponseEvent

def _tool_feedback_to_tool_result_block(payload: Dict[str, Any]) -> Dict[str, Any]:
    tf = payload.get("tool_feedback", {}) if isinstance(payload, dict) else {}
    call_id = tf.get("call_id", "")
    success = bool(tf.get("success", True))
    result = tf.get("result")

    if isinstance(result, (dict, list)):
        out_text = json.dumps(result, ensure_ascii=False)
    elif result is None:
        out_text = ""
    else:
        out_text = str(result)

    return {
        "role": "tool",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": call_id,
                "content": [{"type": "output_text", "text": out_text}],
                "is_error": (False if success else True),
            }
        ],
    }

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

def _to_responses_input(messages: List[Dict[str, str]]) -> ResponseInputParam:
    """为了统一，不允许简单的字符串输入，必须是带 role 的消息列表"""
    items: List[Dict[str, Any]] = []

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "tool":
            obj = None
            if isinstance(content, str):
                try:
                    obj = json.loads(content)
                except Exception:
                    obj = None
            elif isinstance(content, dict):
                obj = content

            if isinstance(obj, dict) and "tool_feedback" in obj:
                items.append(_tool_feedback_to_tool_result_block(obj))
                continue 
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)

        if role in ("system", "user"):
            items.append({
                "role": role,
                "content": [{"type": "input_text", "text": text}],
            })
        elif role == "assistant":
            items.append({
                "role": role,
                "content": [{"type": "output_text", "text": text}],
            })
        else:
            items.append({
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            })

    return cast(ResponseInputParam, items)

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
        api_choice = self._pick_api(params.get("api"))
        model = params.get("model", self._default_model)

        if api_choice == "chat":
            return self._chat_nonstream_sync(messages, model, params)
        elif api_choice == "responses":
            return self._responses_nonstream_sync(messages, model, params)
        else:
            return LLMResponse("")

    #异步非流式,未实现
    async def agenerate_response(self, messages: List[Dict[str, str]], **params) -> LLMResponse: 
        api_choice = self._pick_api(params.get("api"))
        model = params.get("model", self._default_model)

        res = LLMResponse("")
        if api_choice == "chat":
            res = await self._chat_nonstream_async(messages, model, params)
        elif api_choice == "responses":
            res = await self._responses_nonstream_async(messages, model, params)
        return res

    #同步流式,未实现
    def stream_respons(self, messages: List[Dict[str, str]], **params) -> Generator[ResponseEvent, None, None]:
        api_choice = self._pick_api(params.get("api"))
        model = params.get("model", self._default_model)
        if api_choice == "chat":
            for evt in self._chat_stream_responses_sync(messages, model, params):
                if evt.type == "output_text.delta" and isinstance(evt.data, str):
                    yield evt.data
        elif api_choice == "responses":
            for evt in self._responses_stream_responses_sync(messages, model, params):
                if evt.type == "output_text.delta" and isinstance(evt.data, str):
                    yield evt.data

    #暂时不用会话ID
    async def conversations(self) -> str:
        conv = await self._async.conversations.create()
        return conv.id

    #异步流式,目前唯一使用方式
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

    def _responses_nonstream_sync(self, messages, model, params) -> LLMResponse:
        input_items = _to_responses_input(messages)
        resp = self._sync.responses.create(
            model=model,
            input=input_items,
            stream=False,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        return LLMResponse("")

    async def _responses_nonstream_async(self, messages, model, params) -> LLMResponse:
        input_items = _to_responses_input(messages)
        resp = await self._async.responses.create(
            model=model,
            input=input_items,
            stream=False,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        return LLMResponse("")

    # responses 同步 流式
    def _responses_stream_responses_sync(self, messages, model, params) -> Generator[ResponseEvent, None, None]:
        input_items = _to_responses_input(messages)
        stream = self._sync.responses.create(
            model=model,
            input=input_items,
            stream=True,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        yield ResponseEvent.created({})
        for event in stream:
            et = event.type
            if et == "response.output_text.delta":
                delta = getattr(event, "delta", "") or ""
                if delta:
                    yield ResponseEvent.text_delta(delta)
            elif et == "response.completed":
                yield ResponseEvent.completed({})
                break
            elif et == "error":
                yield ResponseEvent.error(getattr(event, "error", "") or "error")
                break

    # responses 异步 流式
    async def _responses_stream_responses_async(self, messages, model, params) -> AsyncGenerator[ResponseEvent, None]:
        #input_items = _to_responses_input(messages)
        stream = await self._async.responses.create(
            model=model,
            input= messages,
            stream=True,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        async for event in stream:
            if event.type == "response.created":
                payload = {"response_id": event.response.id}
                yield ResponseEvent.created(payload)

            elif event.type == "response.failed":
                error_msg = getattr(event, "error", "") or "error"
                yield ResponseEvent.error(error_msg)

            elif event.type == "response.output_item.done":
                yield ResponseEvent.tool_call_ready(event.item)

            elif event.type == "response.output_text.delta":
                yield ResponseEvent.text_delta(event.delta)

            elif event.type == "response.reasoning_text.delta":
                yield ResponseEvent.text_delta(event.delta)

            elif event.type == "response.reasoning_summary_text.delta":
                yield ResponseEvent.reasoning_summary_text_delta(event.delta)

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
                yield ResponseEvent.completed(event.response)
                break

            elif event.type == "error":
                yield ResponseEvent.error(getattr(event, "error", "") or "error")
                break

    def _chat_nonstream_sync(self, messages, model, params) -> LLMResponse:
        chat_msgs = _to_chat_messages(messages)
        resp = self._sync.chat.completions.create(
            model=model,
            messages=chat_msgs,
            stream=False,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        choice = (resp.choices or [None])[0]
        return LLMResponse("")

    async def _chat_nonstream_async(self, messages, model, params) -> LLMResponse:
        chat_msgs = _to_chat_messages(messages)
        resp = await self._async.chat.completions.create(
            model=model,
            messages=chat_msgs,
            stream=False,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        choice = (resp.choices or [None])[0]
        return LLMResponse("")


    #chat 同步 流式
    def _chat_stream_responses_sync(self, messages, model, params) -> Generator[ResponseEvent, None, None]:
        pass

    #chat 异步 流式
    async def _chat_stream_responses_async(self, messages, model, params) -> AsyncGenerator[ResponseEvent, None]:
        chat_msgs = _to_chat_messages(messages)
        stream = await self._async.chat.completions.create(
            model=model,
            messages=chat_msgs,
            stream=True,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        yield ResponseEvent.created({})
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
                    data["arguments"] += tc_delta.function.arguments 
                    yield ResponseEvent.tool_call_delta(data["call_id"], data["name"], tc_delta.function.arguments  or "", data["type"])

            if delta.content:
                text_buffer += delta.content
                yield ResponseEvent.text_delta(delta.content or "")

            finish_reason = chunk.choices[0].finish_reason
            payload = {"content": text_buffer, "finish_reason": finish_reason, "usage": chunk.usage or {}}
            if finish_reason == "tool_calls":
                # tool_call中包含call_id, name, arguments, type
                for tc in tool_calls.values():
                    try:
                        tc["arguments"] = json.loads(tc["arguments"])
                    except json.JSONDecodeError:
                        tc["arguments"] = {}
                    except TypeError:
                        tc["arguments"] = {}
                payload["tool_calls"] = list(tool_calls.values())
                yield ResponseEvent.tool_call_ready(list(tool_calls.values()))

            if finish_reason is not None:
                # 包含tool_calls信息, tool_call中包含call_id, name, arguments, type
                yield ResponseEvent.completed(payload)
