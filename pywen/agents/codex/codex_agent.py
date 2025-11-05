import os
import uuid
import json
import asyncio
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, AsyncGenerator

from pywen.agents.base_agent import BaseAgent
from pywen.llm.llm_client import LLMClient, LLMConfig, LLMMessage
from pywen.utils.token_limits import TokenLimits, ModelProvider
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
    tool_calls: List[Any] = field(default_factory=list)
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
            wire_api="chat",
        )
        self.llm_client = LLMClient(self.llmconfig)
        session_stats.set_current_agent(self.type)
        self.max_task_turns = self.llmconfig.retry
        self.current_task_turns = 0
        self.max_iterations = config.max_iterations
        self.original_user_task = ""
        self.turns: List[Turn] = []
        self.current_turn: Optional[Turn] = None
        self.system_prompt = self._build_system_prompt()

    def get_enabled_tools(self) -> List[str]:
        return ['shell_tool', 'update_plan', 'apply_patch', ]

    def _build_system_prompt(self) -> str:
        import inspect
        agent_dir = Path(inspect.getfile(self.__class__)).parent
        codex_md = agent_dir / "gpt_5_codex_prompt.md"
        if not codex_md.exists():
            raise FileNotFoundError(f"Missing system prompt file '{codex_md}'")
        return codex_md.read_text(encoding="utf-8")

    def _build_messages(self, system_prompt: str, history: list[dict], tail: list[dict] | None = None) -> list[dict]:
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(history)
        if tail:
            msgs.extend(tail)
        return msgs

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

        while self.current_task_turns < self.max_task_turns:
            self.current_task_turns += 1
            if self.current_task_turns == 1:
                yield {"type": "user_message", "data": {"message": user_message, "turn": self.current_task_turns}}
            else:
                yield {
                    "type": "task_continuation",
                    "data": {"message": user_message, "turn": self.current_task_turns, "reason": "Continuing task per CodexAgent policy"},
                }
            turn = Turn(id=str(uuid.uuid4()), user_message= user_message)
            self.current_turn = turn
            self.turns.append(turn)
            total_chunks: List[str] = []
            tool_cycles = 0
            try:
                yield {"type": "turn_start", "data": {"turn_id": turn.id, "message": user_message}}
                user_msg = LLMMessage(role="user", content=user_message)
                self.conversation_history.append(user_msg)
                messages = self._build_messages(
                    system_prompt=self.system_prompt,
                    history=[{"role": m.role, "content": m.content} for m in self.conversation_history],
                )
                params = {"model": model_name, "api":"responses"}
                stage = self._responses_event_convert(turn, messages=messages, params= params)
                                                                                       
                async for ev in stage:
                    et, data = ev.get("type"), ev.get("data", {})
                    if et == "llm_stream_start":
                        yield ev
                    elif et == "llm_chunk":
                        total_chunks.append(data.get("content", ""))
                        yield ev
                    elif et == "tool_call_start":
                        yield ev
                    elif et == "tool_result":
                        tool_cycles += 1
                        yield ev
                        break
                    elif et == "task_complete":
                        turn.add_assistant_response(data.get("reasoning", ""))
                        turn.complete(TurnStatus.COMPLETED)
                        yield ev
                        return
                    elif et == "max_turns_reached":
                        turn.complete(TurnStatus.MAX_ITERATIONS)
                        yield ev
                        return
                    elif et == "error":
                        turn.complete(TurnStatus.ERROR)
                        yield ev
                        return
                else:
                    yield {"type": "error", "data": {"error": "LLM stage ended unexpectedly"}}
                    turn.complete(TurnStatus.ERROR)
                    return

            except Exception as e:
                print("exception !:", str(e))
                yield {"type": "error", "data": {"error": str(e)}}
                turn.complete(TurnStatus.ERROR)
                break

    async def _responses_event_convert(self, turn: Turn, messages, params) -> AsyncGenerator[Dict[str, Any], None]:
        """在这里处理LLM的事件，转换为agent事件流"""
        while turn.iterations < self.max_iterations:
            turn.iterations += 1
            yield {"type": "iteration_start", "data": {"iteration": turn.iterations}}

            collected: List[str] = []

            async for evt in self.llm_client.astream(messages, **params):
                et, data = evt.type , evt.data
                if et == "created":
                    yield {"type": "llm_stream_start", "data": {"message": "LLM response stream started"}}

                elif et == "output_text.delta":
                    if data and isinstance(data, str):
                        collected.append(data)
                        yield {"type": "llm_chunk", "data": {"content": data}}
    
                elif et == "output_item.done":
                    call_id = getattr(data, "call_id", "")
                    args = getattr(data, "args", {})
                    tool_name = getattr(data, "name", "")    
                    yield {"type": "tool_call_start", "data": {"call_id": call_id, "name": tool_name, "arguments": args}}
    
                elif et in ("response.completed", "completed"):
                    final_text = "".join(collected).strip()
                    self.conversation_history.append(LLMMessage(role="assistant", content=final_text))
                    yield {"type": "task_complete", "data": {"total_turns": self._tool_cycles_so_far(), "reasoning": final_text}}
                    return
    
                elif et == "error":
                    yield {"type": "error", "data": {"error": str(data)}}
                    return
            yield {"type": "error", "data": {"error": "LLM stream ended without 'response.completed'"}}

        if turn.iterations >= self.max_iterations and turn.status == TurnStatus.ACTIVE:
            turn.complete(TurnStatus.MAX_ITERATIONS)
            yield {"type": "max_iterations", "data": {"iterations": turn.iterations}}

    def _tool_cycles_so_far(self) -> int:
        return sum(1 for m in self.conversation_history if m.role == "tool")
