from __future__ import annotations
import os,json
from typing import AsyncGenerator, Dict, Generator, Iterator, List, Any, Optional, cast
from openai import OpenAI, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.responses import ResponseInputParam
from .adapter_common import ResponseEvent


def _as_output_text_items(text: str) -> List[Dict[str, str]]:
    return [{"type": "output_text", "text": text}]

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
                "content": _as_output_text_items(out_text),
                "is_error": (False if success else True),
            }
        ],
    }

def _to_chat_messages(messages: List[Dict[str, str]]) -> List[ChatCompletionMessageParam]:
    return cast(
        List[ChatCompletionMessageParam],
        [{"role": m["role"], "content": m["content"]} for m in messages]
    )

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

class ChatAggregationAdapter:
    @staticmethod
    def iter_sync(stream_iter: Iterator) -> Generator[ResponseEvent, None, None]:
        yield ResponseEvent.created({})
        for chunk in stream_iter:
            try:
                delta = chunk.choices[0].delta.content
            except Exception:
                delta = None
            if delta:
                yield ResponseEvent.text_delta(delta)
        yield ResponseEvent.completed({})

    @staticmethod
    async def iter_async(stream_iter) -> AsyncGenerator[ResponseEvent, None]:
        yield ResponseEvent.created({})
        async for chunk in stream_iter:
            try:
                delta = chunk.choices[0].delta.content
            except Exception:
                delta = None
            if delta:
                yield ResponseEvent.text_delta(delta)
        yield ResponseEvent.completed({})

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

    def chat(self, messages: List[Dict[str, str]], **params) -> str:
        api_choice = self._pick_api(params.get("api"))
        model = params.get("model", self._default_model)

        if api_choice == "chat":
            return self._chat_nonstream_sync(messages, model, params)
        if api_choice == "responses":
            return self._responses_nonstream_sync(messages, model, params)

    async def achat(self, messages: List[Dict[str, str]], **params) -> str:
        api_choice = self._pick_api(params.get("api"))
        model = params.get("model", self._default_model)

        if api_choice == "chat":
            return await self._chat_nonstream_async(messages, model, params)
        if api_choice == "responses":
            return await self._responses_nonstream_async(messages, model, params)

    def stream(self, messages: List[Dict[str, str]], **params) -> Generator[str, None, None]:
        api_choice = self._pick_api(params.get("api"))
        model = params.get("model", self._default_model)

        if api_choice == "chat":
            for evt in self._chat_stream_responses_sync(messages, model, params):
                if evt.type == "output_text.delta" and isinstance(evt.data, str):
                    yield evt.data
            return

        if api_choice == "responses":
            for evt in self._responses_stream_responses_sync(messages, model, params):
                if evt.type == "output_text.delta" and isinstance(evt.data, str):
                    yield evt.data
            return

    async def astream(self, messages: List[Dict[str, Any]], **params) -> AsyncGenerator[ResponseEvent, None]:
        api_choice = self._pick_api(params.get("api"))
        model = params.get("model", self._default_model)

        if api_choice == "chat":
            async for evt in self._chat_stream_responses_async(messages, model, params):
                yield evt
            return

        if api_choice == "responses":
            async for evt in self._responses_stream_responses_async(messages, model, params):
                yield evt
            return

    def _pick_api(self, override: Optional[str]) -> str:
        if override in ("responses", "chat", "auto"):
            return override
        return self._wire_api

    def _responses_nonstream_sync(self, messages, model, params) -> str:
        input_items = _to_responses_input(messages)
        resp = self._sync.responses.create(
            model=model,
            input=input_items,
            stream=False,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        return getattr(resp, "output_text", "") or ""

    async def _responses_nonstream_async(self, messages, model, params) -> str:
        input_items = _to_responses_input(messages)
        resp = await self._async.responses.create(
            model=model,
            input=input_items,
            stream=False,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        return getattr(resp, "output_text", "") or ""

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

    async def _responses_stream_responses_async(self, messages, model, params) -> AsyncGenerator[ResponseEvent, None]:
        input_items = _to_responses_input(messages)
        stream = await self._async.responses.create(
            model=model,
            input=input_items,
            stream=True,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        async for event in stream:
            if event.type == "response.created":
                payload = {"response_id": event.response.id}
                yield ResponseEvent.created(payload)

            elif event.type == "response.failed":
                #TODO,完善错误上报
                error_msg = getattr(event, "error", "") or "error"
                yield ResponseEvent.error(error_msg)

            elif event.type == "response.output_item.done":
                yield ResponseEvent.output_item_done({"item_id": event.item})

            elif event.type == "response.output_text.delta":
                yield ResponseEvent.text_delta(event.delta)

            elif event.type == "response.reasoning_summary_text.delta":
                # TODO.
                yield ResponseEvent.text_delta(event.delta)

            elif event.type == "response.reasoning_text.delta":
                # TODO.
                yield ResponseEvent.text_delta(event.delta)

            elif event.type == "response.content_part.done" or \
                event.type == "response.function_call_arguments.delta" or \
                event.type == "custom_tool_call_input.delta" or \
                event.type == "custom_tool_call_input.done" or \
                event.type == "response.in_progress" or \
                event.type == "response.output_text.done":
                # ignore for now
                pass

            elif event.type == "response.output_item.added":
                item = event.item 
                if item.type == "web_search_call":
                    call_id = item.id 
                    yield ResponseEvent.web_search_begin(call_id)

            elif event.type == "response.reasoning_summary_part.added":
                yield ResponseEvent.reasoning_summary_part_added("")

            elif event.type == "response.reasoning_summary_text.done":
                yield ResponseEvent.reasoning_summary_text_done({})

            elif event.type == "response.function_call_arguments.delta":
                yield ResponseEvent.tool_call_delta(event.call_id, event.name, event.delta, kind="function")

            elif event.type == "response.custom_tool_call_input.delta":
                yield ResponseEvent.tool_call_delta(event.item_id, '', event.delta, kind="custom")

            elif event.type == "response.function_call_arguments.done":
                playload = {'item_id': event.item_id, "arguments": event.arguments, "kind": "function"}
                yield ResponseEvent("tool_call.ready", playload)

            elif event.type == "response.custom_tool_call_input.done":
                payload = {'item_id': event.item_id, "input": event.input, "kind": "custom"}
                yield ResponseEvent("tool_call.ready", payload)

            elif event.type == "response.completed":
                yield ResponseEvent.completed({})
                break

            elif event.type == "error":
                yield ResponseEvent.error(getattr(event, "error", "") or "error")
                break

    def _chat_nonstream_sync(self, messages, model, params) -> str:
        chat_msgs = _to_chat_messages(messages)
        resp = self._sync.chat.completions.create(
            model=model,
            messages=chat_msgs,
            stream=False,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        choice = (resp.choices or [None])[0]
        if not choice:
            return ""
        return choice.message.content or ""

    async def _chat_nonstream_async(self, messages, model, params) -> str:
        chat_msgs = _to_chat_messages(messages)
        resp = await self._async.chat.completions.create(
            model=model,
            messages=chat_msgs,
            stream=False,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        choice = (resp.choices or [None])[0]
        if not choice:
            return ""
        return choice.message.content or ""

    def _chat_stream_responses_sync(self, messages, model, params) -> Generator[ResponseEvent, None, None]:
        chat_msgs = _to_chat_messages(messages)
        stream = self._sync.chat.completions.create(
            model=model,
            messages=chat_msgs,
            stream=True,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        yield from ChatAggregationAdapter.iter_sync(stream)

    async def _chat_stream_responses_async(self, messages, model, params) -> AsyncGenerator[ResponseEvent, None]:
        chat_msgs = _to_chat_messages(messages)
        stream = await self._async.chat.completions.create(
            model=model,
            messages=chat_msgs,
            stream=True,
            **{k: v for k, v in params.items() if k not in ("model", "api")}
        )
        async for evt in ChatAggregationAdapter.iter_async(stream):
            yield evt


