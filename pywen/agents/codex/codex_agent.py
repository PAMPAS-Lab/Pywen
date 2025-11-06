import uuid,json
import asyncio
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, AsyncGenerator

from pywen.agents.base_agent import BaseAgent
from pywen.llm.llm_client import LLMClient, LLMConfig, LLMMessage
from pywen.utils.tool_basics import ToolCall
from pywen.core.session_stats import session_stats

class TurnStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    MAX_ITERATIONS = "max_iterations"
    ERROR = "error"

@dataclass
class Turn:
    id: str
    user_message: str
    iterations: int = 0
    status: TurnStatus = TurnStatus.ACTIVE
    assistant_messages: List[str] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[Any] = field(default_factory=list)
    llm_responses: List[Any] = field(default_factory=list)
    total_tokens: int = 0

    def add_assistant_response(self, resp_text: str):
        self.llm_responses.append(resp_text)
        if resp_text:
            self.assistant_messages.append(resp_text)

    def add_tool_call(self, tc):
        self.tool_calls.append(tc)

    def add_tool_result(self, tr):
        self.tool_results.append(tr)

    def complete(self, status: TurnStatus):
        self.status = status

class CodexAgent(BaseAgent):
    def __init__(self, config, hook_mgr, cli_console=None):
        super().__init__(config, hook_mgr, cli_console)
        self.type = "CodexAgent"
        self.llmconfig = LLMConfig(
            provider=config.model_config.provider.value,
            api_key=config.model_config.api_key,
            base_url=config.model_config.base_url,
            model="gpt-5-codex",
            wire_api="responses",
        )
        self.llm_client = LLMClient(self.llmconfig)
        session_stats.set_current_agent(self.type)
        self.max_task_turns = self.llmconfig.retry
        self.max_iterations = config.max_iterations
        self.current_task_turns = 0
        self.original_user_task = ""
        self.turns: List[Turn] = []
        self.current_turn: Optional[Turn] = None
        self.system_prompt = self._build_system_prompt()
        self.conversation_history: List[LLMMessage] = []

    def get_enabled_tools(self) -> List[str]:
        return ['shell_tool', 'update_plan', 'apply_patch', ]

    async def run(self, user_message: str) -> AsyncGenerator[Dict[str, Any], None]:
        model_name = self.llmconfig.model
        provider = self.llmconfig.provider
        max_tokens = 200000
        if self.cli_console:
            self.cli_console.set_max_context_tokens(max_tokens)
        self.original_user_task = user_message
        self.current_task_turns = 0
        session_stats.record_task_start(self.type)
        self.trajectory_recorder.start_recording(
            task=user_message, provider=provider, model=model_name, max_steps=self.max_iterations
        )
        self.conversation_history.append(LLMMessage(role="user", content=user_message))

        while self.current_task_turns < self.max_task_turns:
            self.current_task_turns += 1
            if self.current_task_turns == 1:
                yield {"type": "user_message", "data": {"message": user_message, "turn": self.current_task_turns}}

            turn = Turn(id=str(uuid.uuid4()), user_message= user_message)
            self.current_turn = turn
            self.turns.append(turn)
            total_chunks: List[str] = []
            messages = self._build_messages(
                system_prompt=self.system_prompt,
                history=self.conversation_history,
            )
            params = {"model": model_name, "api":"responses"}

            stage = self._responses_event_process(turn, messages=messages, params= params)
                                                                                   
            async for ev in stage:
                et, data = ev.get("type"), ev.get("data", {})
                if et == "llm_stream_start" or et == "tool_call_start":
                    yield ev
                elif et == "llm_chunk":
                    total_chunks.append(data.get("content", ""))
                    yield ev
                elif et == "tool_result":
                    yield ev
                    break
                elif et == "task_complete":
                    turn.add_assistant_response(data.get("reasoning", ""))
                    turn.complete(TurnStatus.COMPLETED)
                    yield ev
                    break
                elif et == "max_turns_reached":
                    turn.complete(TurnStatus.MAX_ITERATIONS)
                    yield ev
                    break
                elif et == "error":
                    turn.complete(TurnStatus.ERROR)
                    yield ev
                    return

    def _build_system_prompt(self) -> str:
        import inspect
        agent_dir = Path(inspect.getfile(self.__class__)).parent
        codex_md = agent_dir / "gpt_5_codex_prompt.md"
        if not codex_md.exists():
            raise FileNotFoundError(f"Missing system prompt file '{codex_md}'")
        return codex_md.read_text(encoding="utf-8")

    def _build_messages(self, system_prompt: str, history: List[LLMMessage]) -> List[Dict[str, Any]]:
        msgs: List[Dict[str, Any]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})

        for m in history:
            one: Dict[str, Any] = {"role": m.role}
            if m.content is not None:
                one["content"] = m.content
            if m.tool_call_id:
                one["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                one["tool_calls"] = []
                for tc in m.tool_calls:
                    payload: Dict[str, Any] = {
                        "call_id": getattr(tc, "call_id", None),
                        "name": getattr(tc, "name", None),
                    }
                    args = getattr(tc, "arguments", None)
                    if args is not None:
                        payload["arguments"] = args
                    inp = getattr(tc, "input", None)
                    if inp is not None:
                        payload["input"] = inp
                    one["tool_calls"].append(payload)
            msgs.append(one)
        return msgs

    async def _responses_event_process(self, turn: Turn, messages, params) -> AsyncGenerator[Dict[str, Any], None]:
        """在这里处理LLM的事件，转换为agent事件流"""
        iterations = 0
        while iterations < self.max_iterations:
            iterations += 1
            turn.iterations = iterations
            collected_text_parts: List[str] = []
            tool_calls_buffer: List[ToolCall] = []

            async for evt in self.llm_client.astream_response(messages, **params):
                if evt.type == "created":
                    yield {"type": "llm_stream_start", "data": {"message": "LLM response stream started"}}

                elif evt.type == "output_text.delta":
                    collected_text_parts.append(evt.data)
                    yield {"type": "llm_chunk", "data": {"content": data}}
    
                elif evt.type == "output_item.done":
                    call_id = getattr(data, "call_id", "")
                    tool_name = getattr(data, "name", "")    
                    tc = None
                    if evt.item == "function_call":
                        args = getattr(data, "arguments", {})
                        tc = ToolCall(call_id= call_id, type = ftype, name = tool_name, arguments = args)
                    elif ftype == "custom_tool_call":
                        input = getattr(data, "input", "")
                        tc = ToolCall(call_id= call_id, type = ftype, name = tool_name, input = input)
                    else:
                        continue
                    tool_calls_buffer.append(tc)
                    turn.add_tool_call(tc)

                    async for tool_event in self._process_one_tool_call(turn, tc):
                        yield tool_event

                elif evt.type == "completed":
                    yield {"type": "task_complete", "data": {"status": "completed"}}
                    return
                elif evt.type == "error":
                    yield {"type": "error", "data": {"error": str(data)}}
                    return

            yield {"type": "error", "data": {"error": "LLM stream ended without 'response.completed'"}}
            return 

        turn.complete(TurnStatus.MAX_ITERATIONS)
        yield {"type": "max_iterations", "data": {"iterations": turn.iterations}}

    def _tool_cycles_so_far(self) -> int:
        return sum(1 for m in self.conversation_history if m.role == "tool")

    async def _process_one_tool_call(self, turn: Turn, tool_call) -> AsyncGenerator[Dict[str, Any], None]:
        turn.add_tool_call(tool_call)
        payload = { "call_id": tool_call.call_id, "name": tool_call.name, "arguments": tool_call.arguments}
        yield {"type": "tool_call_start", "data": payload}
        if not self.cli_console:
            return
        tool = self.tool_registry.get_tool(tool_call.name)
        if not tool:
            return
        confirmation_details = await tool.get_confirmation_details(**tool_call.arguments)
        if not  confirmation_details:
            return
        confirmed = await self.cli_console.confirm_tool_call(tool_call, tool)
        if not confirmed:
            tool_msg = LLMMessage(role="tool", content="Tool execution was cancelled by user", tool_call_id=tool_call.call_id)
            self.conversation_history.append(tool_msg)
            payload = {"call_id": tool_call.call_id, 
                        "name": tool_call.name, 
                        "result": "Tool execution rejected by user",
                        "success":False,
                        "error": "Tool execution rejuected by user",
                        }
            yield {"type": "tool_result", "data": payload}
            return
        try:
            results = await self.tool_executor.execute_tools([tool_call], self.type)
            result = results[0]
            payload = {"call_id": tool_call.call_id, "name": tool_call.name, "result": result.result,
                       "success": result.success, "error": result.error, "arguments": tool_call.arguments}
            yield {"type": "tool_result", "data": payload}
            turn.add_tool_result(result)
            if isinstance(result.result, dict):
                content = result.result.get('summary', str(result.result)) or str(result.error)
            else:
                content = str(result.result) or str(result.error)
            tool_msg = LLMMessage(role="tool", content=content, tool_call_id=tool_call.call_id)
            self.conversation_history.append(tool_msg)

        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            yield {"type": "tool_error", "data": {"call_id": tool_call.call_id, "name": tool_call.name, "error": error_msg}}
            
            tool_msg = LLMMessage(role="tool", content=error_msg, tool_call_id=tool_call.call_id)
            self.conversation_history.append(tool_msg)

