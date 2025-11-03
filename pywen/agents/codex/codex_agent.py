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
            wire_api="responses",
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
        default_dir = Path.home() / ".pywen"
        default_md = default_dir / "codex_system.md"
        md_env = os.environ.get("PYWEN_CODEX_SYSTEM_MD", "").strip().lower()
        use_external = False
        md_path = Path()

        if md_env and md_env not in {"0", "false", "1", "true"}:
            md_path = Path(os.environ["PYWEN_CODEX_SYSTEM_MD"]).expanduser().resolve()
            use_external = True
        elif md_env in {"1", "true"}:
            md_path = default_md
            use_external = True
        elif not md_env:
            if codex_md.exists():
                md_path = codex_md
                use_external = True

        if use_external:
            if not md_path.exists():
                raise FileNotFoundError(f"Missing system prompt file '{md_path}'")
            return md_path.read_text(encoding="utf-8")

        tools = "\n".join([f"- **{t.name}**: {t.description}" for t in self.tool_registry.list_tools()])
        return f"""
You are PYWEN-CODEX, a CLI-first software engineering agent.
Be surgical, safe, and fast. Use tools when acting on files, running commands, or browsing.
Prefer minimal deltas, strong reasoning, and explicit verification.

# Rules
- Never assume dependencies or commands; inspect the repo first.
- Explain risky shell commands briefly before execution.
- Keep outputs concise; prioritize actions and diffs over prose.
- Use absolute paths for file tools.
- Record every LLM interaction and tool result (the recorder is already wired).

# Available Tools
{tools}

# Workflow
1) Understand: scan codebase and context with grep/glob/read tools.
2) Plan: outline a short, concrete action list.
3) Implement: edit/write/run as needed.
4) Verify: run tests/lints/builds as the project prescribes.
5) Conclude: stop when the task is satisfied or blocked by missing info.

# Git Awareness
If a git repo is detected, follow project conventions for commits, diffs, and messages.
""".strip()

    async def run(self, user_message: str) -> AsyncGenerator[Dict[str, Any], None]:
        model_name = self.llmconfig.model
        provider = self.llmconfig.provider
        max_tokens = 400000
        if self.cli_console:
            self.cli_console.set_max_context_tokens(max_tokens)

        self.original_user_task = user_message
        self.current_task_turns = 0
        session_stats.record_task_start(self.type)

        self.trajectory_recorder.start_recording(
            task=user_message, provider=provider, model=model_name, max_steps=self.max_iterations
        )

        current_message = user_message

        while self.current_task_turns < self.max_task_turns:
            self.current_task_turns += 1

            if self.current_task_turns == 1:
                yield {"type": "user_message", "data": {"message": current_message, "turn": self.current_task_turns}}

            yield {
                "type": "task_continuation",
                "data": {"message": current_message, "turn": self.current_task_turns, "reason": "Continuing task per CodexAgent policy"},
            }

            turn = Turn(id=str(uuid.uuid4()), user_message=current_message)
            self.current_turn = turn
            self.turns.append(turn)

            try:
                self.conversation_history.append(LLMMessage(role="system", content=self.system_prompt))
                self.conversation_history.append(LLMMessage(role="user", content=current_message))

                total_chunks: List[str] = []
                tool_cycles = 0
                while True:
                    stage = self._run_responses_stage()
                    async for ev in stage:
                        et, data = ev["type"], ev["data"]
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
                yield {"type": "error", "data": {"error": str(e)}}
                turn.complete(TurnStatus.ERROR)
                break

    def _prepare_messages_for_iteration(self) -> List[Dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in self.conversation_history]

    async def _run_responses_stage(self) -> AsyncGenerator[Dict[str, Any], None]:
        messages = self._prepare_messages_for_iteration()
        params = {"api": "responses", "model": self.llmconfig.model}
        yield {"type": "llm_stream_start", "data": {}}
        collected: List[str] = []
        tool_cycles_guard = getattr(self, "max_iterations", 1_000_000)

        async for evt in self.llm_client.astream(messages, **params):
            et = evt.type
            data = getattr(evt, "data", {}) or {}

            if et in ("response.output_text.delta", "output_text.delta"):
                delta_text = data if isinstance(data, str) else data.get("delta", "")
                if delta_text:
                    collected.append(delta_text)
                    yield {"type": "llm_chunk", "data": {"content": delta_text}}

            elif et == "tool_call.ready":
                if self._tool_cycles_so_far() >= tool_cycles_guard:
                    yield {"type": "max_turns_reached", "data": {"total_turns": self._tool_cycles_so_far(), "max_turns": tool_cycles_guard}}
                    return

                call_id = data.get("call_id") or ""
                args = data.get("args") or {}
                tool_name = data.get("name") or data.get("kind") or "__tool__"

                yield {"type": "tool_call_start", "data": {"call_id": call_id, "name": tool_name, "arguments": args}}

                success, result, error = await self._invoke_tool_safe(tool_name, args)
                yield {"type": "tool_result", "data": {
                    "call_id": call_id, "name": tool_name, "result": result, "success": success, "error": error, "arguments": args
                }}

                tool_feedback_text = self._format_tool_feedback_text(call_id, result, success, error)
                self.conversation_history.append(LLMMessage(role="tool", content=tool_feedback_text))

                return

            elif et in ("response.completed", "completed"):
                final_text = "".join(collected).strip()
                self.conversation_history.append(LLMMessage(role="assistant", content=final_text))
                yield {"type": "task_complete", "data": {"total_turns": self._tool_cycles_so_far(), "reasoning": final_text}}
                return

            elif et == "error":
                yield {"type": "error", "data": {"error": str(data)}}
                return

        yield {"type": "error", "data": {"error": "LLM stream ended without 'response.completed'"}}

    def _tool_cycles_so_far(self) -> int:
        return sum(1 for m in self.conversation_history if m.role == "tool")

    async def _invoke_tool_safe(self, name: str, args: Dict[str, Any]):
        #改造，工具执行
        try:
            tool = self.tool_registry.get(name)
            if tool is None:
                return False, None, f"tool '{name}' not found"
            if hasattr(tool, "run_async") and asyncio.iscoroutinefunction(tool.run_async):
                result = await tool.run_async(**args)
                return True, result, None
            elif hasattr(tool, "run"):
                result = tool.run(**args)
                return True, result, None
            else:
                return False, None, f"tool '{name}' has no runnable interface"
        except Exception as e:
            return False, None, f"{type(e).__name__}: {e}"

    def _format_tool_feedback_text(self, call_id: str, result: Any, success: bool, error: Optional[str]) -> str:
        payload = {
            "tool_feedback": {
                "call_id": call_id,
                "success": success,
                "error": error,
                "result": result,
            }
        }
        try:
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            return f'{{"tool_feedback": {{"call_id":"{call_id}","success":{success},"error":{json.dumps(error)}, "result": "{str(result)}"}}}}'

