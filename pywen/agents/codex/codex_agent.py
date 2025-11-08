import json
from pathlib import Path
from typing import Dict, List, Mapping, Any, AsyncGenerator

from pywen.agents.base_agent import BaseAgent
from pywen.llm.llm_client import LLMClient, LLMConfig, LLMMessage
from pywen.utils.tool_basics import ToolCall
from pywen.core.session_stats import session_stats

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
        self.current_turn_index = 0
        self.original_user_task = ""
        self.system_prompt = self._build_system_prompt()
        self.conversation_history: List[LLMMessage] = []
        self.tools = self.tools_format_convert()

    def get_enabled_tools(self) -> List[str]:
        return ['shell_tool', 'update_plan', 'apply_patch',]

    def tools_format_convert(self) -> List[Dict[str, Any]]:
        tool_list = []
        tools = self.tool_registry.list_tools()
        for t in tools:
            codex_tool = t.build()
            tool_list.append(codex_tool)
        return tool_list

    async def run(self, user_message: str) -> AsyncGenerator[Dict[str, Any], None]:
        model_name = self.llmconfig.model
        provider = self.llmconfig.provider
        max_tokens = 200000
        if self.cli_console:
            self.cli_console.set_max_context_tokens(max_tokens)
        self.original_user_task = user_message
        self.current_turn_index = 0
        session_stats.record_task_start(self.type)
        self.trajectory_recorder.start_recording(
            task=user_message, provider=provider, model=model_name, max_steps=self.max_iterations
        )
        self.conversation_history.append(LLMMessage(role="user", content=user_message))

        while self.current_turn_index < self.max_task_turns:
            self.current_turn_index += 1
            if self.current_turn_index == 1:
                yield {"type": "user_message", "data": {"message": user_message, "turn": self.current_turn_index}}
            messages = self._build_messages(
                system_prompt=self.system_prompt,
                history=self.conversation_history,
            )
            params = {"model": model_name, "api":"responses", "tools" : self.tools}
            stage = self._responses_event_process(messages=messages, params=params)
            async for ev in stage:
                yield ev

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

    async def _responses_event_process(self, messages, params) -> AsyncGenerator[Dict[str, Any], None]:
        """在这里处理LLM的事件，转换为agent事件流"""

        async for evt in self.llm_client.astream_response(messages, **params):
            if evt.type == "created":
                yield {"type": "llm_stream_start", "data": {"message": "LLM response stream started"}}

            elif evt.type == "output_text.delta":
                yield {"type": "llm_chunk", "data": {"content": evt.data}}
    
            elif evt.type == "tool_call.ready":
                tool_args = evt.data.get('args')
                if evt.data.get('kind') == "custom":
                    tool_args = {
                            "patch" : evt.data.get('args'),
                            }
                tc = ToolCall(
                        call_id = evt.data.get("call_id"), 
                        name = evt.data.get('name'), 
                        arguments = tool_args,
                        type = evt.data.get('kind'),
                    )
                async for tool_event in self._process_one_tool_call(tc):
                    yield tool_event

            elif evt.type == "completed":
                yield {"type": "task_complete", "data": {"status": "completed"}}
                return

            elif evt.type == "error":
                yield {"type": "error", "data": {"error": str(evt.data)}}
                return

    async def _process_one_tool_call(self, tool_call) -> AsyncGenerator[Dict[str, Any], None]:
        tool = self.tool_registry.get_tool(tool_call.name)
        if not tool:
            return
        if not self.cli_console:
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

