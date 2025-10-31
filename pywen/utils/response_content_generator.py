"""Response API client implementation mimicking openai_api.py responses.create() interface."""

import ast
import json
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

import openai

from .base_content_generator import ContentGenerator
from .llm_config import Config, GenerateContentConfig
from .llm_basics import LLMMessage, LLMResponse, LLMUsage
from .tool_basics import ToolCall
from pywen.tools.base import Tool



class ResponseContentGenerator(ContentGenerator):
    """Content generator using OpenAI's responses.create() API interface.

    This mimics the interface used in agent-arxiv-daily/latex_analysis/openai_api.py,
    which uses client.responses.create() instead of the standard chat.completions API.
    """

    def __init__(self, config: Config):
        super().__init__(config)
        self.api_key = config.api_key
        self.base_url = config.model_params.base_url or "http://47.99.91.71:8080/openai"
        self.model_name = config.model_params.model

        if not self.api_key:
            raise ValueError("API key is required")

        # Initialize OpenAI client with custom parameters
        client_kwargs = {
            "api_key": self.api_key,
            "timeout": 120.0,
            "max_retries": 3,
        }

        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = openai.AsyncOpenAI(**client_kwargs)

    def _convert_messages_to_input_format(self, messages: List[LLMMessage]) -> List[Dict[str, Any]]:
        """Convert LLM messages to input format for responses.create() API.

        The responses.create() API uses 'input' parameter instead of 'messages'.
        """
        input_messages = []

        for message in messages:
            # Tool responses need to be represented as function_call_output items
            if message.role == "tool":
                if not message.tool_call_id:
                    continue
                input_messages.append({
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content or ""
                })
                continue

            input_message = {
                "role": message.role,
                "content": message.content or "",
            }

            # Handle tool calls if present
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    input_messages.append({
                        "type": "function_call",
                        "call_id": tool_call.call_id,
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments or {})
                    })

            # Handle tool call ID for tool response messages
            if message.tool_call_id:
                input_message["tool_call_id"] = message.tool_call_id

            # Avoid adding empty assistant messages when only tool calls are present
            if message.content or message.role != "assistant":
                input_messages.append(input_message)

        return input_messages

    def _convert_tools_to_input_format(self, tools: List[Tool]) -> List[Dict[str, Any]]:
        """Convert internal tool definitions to Responses API format."""
        converted_tools = []

        for tool in tools:
            converted_tools.append({
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters
            })

        return converted_tools

    def _fix_json_format(self, json_str: str) -> str:
        """Attempt to fix common JSON formatting issues."""
        fixed = json_str.strip()

        # Remove wrapping quotes if present
        if fixed.startswith('"{') and fixed.endswith('}"'):
            fixed = fixed[1:-1]

        # Replace single quotes around keys/values with double quotes when safe
        try:
            fixed = re.sub(r"'(\w+)':", r'"\1":', fixed)
            fixed = re.sub(r": '([^']*)'", r': "\1"', fixed)
        except re.error:
            pass

        return fixed

    def _safe_json_parse(self, json_str: str) -> Dict[str, Any]:
        """Safely parse JSON string, handling Python dict formats."""
        if not json_str or not json_str.strip():
            return {}

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(json_str)
            except (ValueError, SyntaxError):
                fixed_str = self._fix_json_format(json_str)
                try:
                    return json.loads(fixed_str)
                except json.JSONDecodeError:
                    try:
                        return ast.literal_eval(fixed_str)
                    except (ValueError, SyntaxError):
                        print(f"Warning: Could not parse tool arguments: {json_str[:200]}...")
                        return {}

    def _parse_response_object(self, response: Any) -> LLMResponse:
        """Convert Responses API object to internal LLMResponse."""
        content_parts: List[str] = []
        tool_calls: List[ToolCall] = []

        # Extract textual content
        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", None)

            if item_type == "message":
                for content_part in getattr(item, "content", []) or []:
                    if getattr(content_part, "type", None) == "output_text":
                        content_text = getattr(content_part, "text", "")
                        if content_text:
                            content_parts.append(content_text)

            elif item_type == "function_call":
                call_id = getattr(item, "call_id", None) or getattr(item, "id", None) or f"call_{len(tool_calls)}"
                name = getattr(item, "name", "")
                arguments_str = getattr(item, "arguments", "") or "{}"
                arguments = self._safe_json_parse(arguments_str)

                tool_calls.append(
                    ToolCall(
                        call_id=call_id,
                        name=name,
                        arguments=arguments
                    )
                )

        usage = None
        if getattr(response, "usage", None):
            usage = LLMUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.total_tokens
            )

        finish_reason = "tool_calls" if tool_calls else "stop"
        content = "".join(content_parts).strip()

        return LLMResponse(
            content=content,
            model=getattr(response, "model", self.model_name),
            finish_reason=finish_reason,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage
        )

    async def generate_content(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Tool]] = None,
        config: Optional[GenerateContentConfig] = None
    ) -> LLMResponse:
        """Generate content using responses.create() API (non-streaming).

        Args:
            messages: List of LLM messages
            tools: Optional list of tools (not supported by responses API)
            config: Optional generation configuration

        Returns:
            LLMResponse with generated content
        """
        try:
            request_params: Dict[str, Any] = {
                "model": self.model_name,
                "input": self._convert_messages_to_input_format(messages),
                "stream": True,
            }

            temperature = None
            max_tokens = None
            top_p = None

            if config and config.temperature is not None:
                temperature = config.temperature
            elif self.config.model_params.temperature is not None:
                temperature = self.config.model_params.temperature

            if config and config.max_output_tokens is not None:
                max_tokens = config.max_output_tokens
            elif self.config.model_params.max_tokens is not None:
                max_tokens = self.config.model_params.max_tokens

            if config and config.top_p is not None:
                top_p = config.top_p
            elif self.config.model_params.top_p is not None:
                top_p = self.config.model_params.top_p

            if temperature is not None:
                request_params["temperature"] = temperature
            if max_tokens is not None:
                request_params["max_output_tokens"] = max_tokens
            if top_p is not None:
                request_params["top_p"] = top_p

            if tools:
                request_params["tools"] = self._convert_tools_to_input_format(tools)
                request_params["tool_choice"] = "auto"

            stream = await self.client.responses.create(**request_params)

            accumulated_content = ""
            tool_meta: Dict[str, Dict[str, Any]] = {}
            tool_arguments: Dict[str, str] = {}
            final_response_obj: Optional[Any] = None

            try:
                async for event in stream:
                    event_type = getattr(event, "type", None)

                    if event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            accumulated_content += delta

                    elif event_type == "response.output_item.added":
                        item = getattr(event, "item", None)
                        if item and getattr(item, "type", None) == "function_call":
                            item_id = getattr(item, "id", None) or getattr(item, "call_id", None) or f"call_{len(tool_meta)}"
                            call_id = getattr(item, "call_id", None) or item_id
                            name = getattr(item, "name", "")
                            tool_meta[item_id] = {
                                "call_id": call_id,
                                "name": name,
                            }
                            arguments = getattr(item, "arguments", "")
                            if arguments:
                                tool_arguments[item_id] = arguments

                    elif event_type == "response.function_call.arguments.delta":
                        item_id = getattr(event, "item_id", None)
                        delta = getattr(event, "delta", "")
                        if item_id and delta:
                            tool_arguments[item_id] = tool_arguments.get(item_id, "") + delta

                    elif event_type == "response.function_call.arguments.done":
                        item_id = getattr(event, "item_id", None)
                        arguments = getattr(event, "arguments", "")
                        if item_id:
                            tool_arguments[item_id] = arguments or tool_arguments.get(item_id, "")

                    elif event_type == "response.completed":
                        final_response_obj = getattr(event, "response", None)
                        break

                    elif event_type == "response.error":
                        error_payload = getattr(event, "error", None)
                        raise RuntimeError(f"Streaming error: {error_payload}")

            finally:
                try:
                    await stream.aclose()
                except Exception:
                    pass

            if final_response_obj:
                llm_response = self._parse_response_object(final_response_obj)
            else:
                llm_response = LLMResponse(
                    content=accumulated_content.strip(),
                    model=self.model_name,
                    finish_reason="stop",
                    usage=None
                )

            if accumulated_content:
                llm_response.content = accumulated_content.strip()

            if (not llm_response.tool_calls) and tool_meta:
                collected_tool_calls: List[ToolCall] = []
                for item_id, meta in tool_meta.items():
                    arguments = self._safe_json_parse(tool_arguments.get(item_id, "{}"))
                    collected_tool_calls.append(
                        ToolCall(
                            call_id=meta.get("call_id") or item_id,
                            name=meta.get("name", ""),
                            arguments=arguments
                        )
                    )
                if collected_tool_calls:
                    llm_response.tool_calls = collected_tool_calls
                    llm_response.finish_reason = "tool_calls"

            if llm_response.usage is None:
                input_tokens = sum(len(msg.content or "") for msg in messages) // 4
                output_tokens = len(llm_response.content or "") // 4
                llm_response.usage = LLMUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens
                )

            return llm_response

        except Exception as e:
            raise Exception(f"Response API error: {str(e)}")

    async def generate_content_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Tool]] = None,
        config: Optional[GenerateContentConfig] = None
    ) -> AsyncGenerator[LLMResponse, None]:
        """Generate streaming content with tool call support."""
        try:
            request_params: Dict[str, Any] = {
                "model": self.model_name,
                "input": self._convert_messages_to_input_format(messages),
                "stream": True,
            }

            temperature = None
            max_tokens = None
            top_p = None

            if config and config.temperature is not None:
                temperature = config.temperature
            elif self.config.model_params.temperature is not None:
                temperature = self.config.model_params.temperature

            if config and config.max_output_tokens is not None:
                max_tokens = config.max_output_tokens
            elif self.config.model_params.max_tokens is not None:
                max_tokens = self.config.model_params.max_tokens

            if config and config.top_p is not None:
                top_p = config.top_p
            elif self.config.model_params.top_p is not None:
                top_p = self.config.model_params.top_p

            if temperature is not None:
                request_params["temperature"] = temperature
            if max_tokens is not None:
                request_params["max_output_tokens"] = max_tokens
            if top_p is not None:
                request_params["top_p"] = top_p

            if tools:
                request_params["tools"] = self._convert_tools_to_input_format(tools)
                request_params["tool_choice"] = "auto"

            stream = await self.client.responses.create(**request_params)

            accumulated_content = ""
            tool_meta: Dict[str, Dict[str, Any]] = {}
            tool_arguments: Dict[str, str] = {}
            final_response_obj: Optional[Any] = None

            try:
                async for event in stream:
                    event_type = getattr(event, "type", None)

                    if event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            accumulated_content += delta
                            yield LLMResponse(
                                content=accumulated_content,
                                model=self.model_name,
                                finish_reason=None,
                                usage=None
                            )

                    elif event_type == "response.output_item.added":
                        item = getattr(event, "item", None)
                        if item and getattr(item, "type", None) == "function_call":
                            item_id = getattr(item, "id", None) or getattr(item, "call_id", None) or f"call_{len(tool_meta)}"
                            call_id = getattr(item, "call_id", None) or item_id
                            name = getattr(item, "name", "")
                            if name and name != "think_tool":
                                print(f"🔧 Calling {name} tool...")

                            tool_meta[item_id] = {
                                "call_id": call_id,
                                "name": name,
                            }
                            arguments = getattr(item, "arguments", "")
                            if arguments:
                                tool_arguments[item_id] = arguments

                    elif event_type == "response.function_call.arguments.delta":
                        item_id = getattr(event, "item_id", None)
                        delta = getattr(event, "delta", "")
                        if item_id and delta:
                            tool_arguments[item_id] = tool_arguments.get(item_id, "") + delta

                    elif event_type == "response.function_call.arguments.done":
                        item_id = getattr(event, "item_id", None)
                        arguments = getattr(event, "arguments", "")
                        if item_id:
                            tool_arguments[item_id] = arguments or tool_arguments.get(item_id, "")

                    elif event_type == "response.completed":
                        final_response_obj = getattr(event, "response", None)
                        break

                    elif event_type == "response.error":
                        error_payload = getattr(event, "error", None)
                        raise RuntimeError(f"Streaming error: {error_payload}")

            finally:
                try:
                    await stream.aclose()
                except Exception:
                    pass

            if final_response_obj:
                final_response = self._parse_response_object(final_response_obj)
            else:
                final_response = LLMResponse(
                    content=accumulated_content.strip(),
                    model=self.model_name,
                    finish_reason="stop",
                    usage=None
                )

            # Merge accumulated tool calls if the final response lacks them
            if (not final_response.tool_calls) and tool_meta:
                collected_tool_calls: List[ToolCall] = []
                for item_id, meta in tool_meta.items():
                    arguments = self._safe_json_parse(tool_arguments.get(item_id, "{}"))
                    collected_tool_calls.append(
                        ToolCall(
                            call_id=meta.get("call_id") or item_id,
                            name=meta.get("name", ""),
                            arguments=arguments
                        )
                    )
                if collected_tool_calls:
                    final_response.tool_calls = collected_tool_calls
                    final_response.finish_reason = "tool_calls"

            if accumulated_content:
                final_response.content = accumulated_content

            if final_response.usage is None:
                input_tokens = sum(len(msg.content or "") for msg in messages) // 4
                output_tokens = len(final_response.content or "") // 4
                final_response.usage = LLMUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens
                )

            yield final_response

        except Exception as e:
            raise Exception(f"Response API streaming error: {str(e)}")

    async def count_tokens(self, messages: List[LLMMessage]) -> int:
        """Count tokens in messages (approximate).

        Uses simple character-based approximation since the responses API
        doesn't provide a direct token counting endpoint.
        """
        total_chars = sum(len(msg.content or "") for msg in messages)
        return total_chars // 4

    async def embed_content(self, content: str) -> List[float]:
        """Generate embeddings for content.

        Note: This uses the standard OpenAI embeddings endpoint,
        not the responses API.
        """
        try:
            response = await self.client.embeddings.create(
                model=self.config.embedding_model or "text-embedding-ada-002",
                input=content
            )
            return response.data[0].embedding
        except Exception as e:
            raise Exception(f"Embedding API error: {str(e)}")


# Simple synchronous wrapper for compatibility with original openai_api.py
class ResponseClient:
    """Synchronous wrapper for ResponseContentGenerator.

    Provides a simple interface similar to the original OpenAIClient
    from agent-arxiv-daily/latex_analysis/openai_api.py.
    """

    def __init__(self, api_key: str, base_url: str = "http://47.99.91.71:8080/openai", model_name: str = "gpt-5"):
        """Initialize Response client.

        Args:
            api_key: API key for authentication
            base_url: Base URL for API endpoint
            model_name: Model to use
        """
        from .llm_config import Config, ModelParameters, AuthType

        config = Config(
            auth_type=AuthType.API_KEY,
            api_key=api_key,
            model_params=ModelParameters(
                model=model_name,
                base_url=base_url
            )
        )

        self.generator = ResponseContentGenerator(config)
        self.model_name = model_name

    async def send_message(self, prompt_content: str) -> str:
        """Send a message and get response.

        Args:
            prompt_content: The prompt/message to send

        Returns:
            Response text
        """
        from .llm_basics import LLMMessage

        messages = [LLMMessage(role="user", content=prompt_content)]
        response = await self.generator.generate_content(messages)
        return response.content
