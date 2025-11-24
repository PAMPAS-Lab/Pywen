import json,os
from pathlib import Path
from typing import Dict, List, Mapping, Literal, Any, AsyncGenerator
from pydantic import BaseModel
from pywen.agents.base_agent import BaseAgent
from pywen.llm.llm_client import LLMClient 
from pywen.utils.tool_basics import ToolCall
from pywen.utils.llm_basics import LLMMessage
from pywen.config.token_limits import TokenLimits 
from pywen.core.session_stats import session_stats
from pywen.core.tool_registry2 import list_tools_for_provider, get_tool

MessageRole = Literal["system", "developer", "user", "assistant"]
HistoryItem = Dict[str, Any]

class History:
    def __init__(self, system_prompt: str):
        self._items: List[HistoryItem] = [
            {"type": "message", "role": "system", "content": system_prompt}
        ]

    def replace_system(self, content: str) -> None:
        self._items[0] = {"type": "message", "role": "system", "content": content}

    def add_message(self, role: MessageRole, content: Any) -> None:
        if role == "system":
            raise ValueError("system 只能在第 0 条；请用 replace_system()。")
        self._items.append({"type": "message", "role": role, "content": content})

    def add_item(self, item: Any) -> None:
        """当参数是Pydantic模型时，转换为字典后添加"""
        if isinstance(item, BaseModel):
            data = item.model_dump(exclude_none=True)
            self._items.append(data)
        elif isinstance(item, dict):
            self._items.append(item)

    def add_items(self, items: List[Any]) -> None:
        for item in items:
            self.add_item(item)

    def to_responses_input(self) -> List[HistoryItem]:
        def _remove_none(items: List[Any]) -> List[Any]:
            return [x for x in items if x is not None]
        return _remove_none(self._items)

class CodexAgent(BaseAgent):
    def __init__(self, config, hook_mgr, cli_console=None):
        super().__init__(config, hook_mgr, cli_console)
        self.type = "CodexAgent"
        self.llm_client = LLMClient(self.config.active_model)
        session_stats.set_current_agent(self.type)
        self.turn_cnt_max = config.max_turns
        self.turn_index = 0
        self.history: History = History(system_prompt= self._build_system_prompt())
        self.tools = [tool.build("codex") for tool in list_tools_for_provider("codex")]
        self.current_task = None

    def get_enabled_tools(self) -> List[str]:
        return ['shell_tool', 'update_plan', 'apply_patch',]

    def build_environment_context(self, cwd: str, approval_policy: str = "on-request", 
            sandbox_mode: str = "workspace-write", network_access: str = "restricted", shell: str = "zsh", ) -> Dict:
        content = (
            "<environment_context>\n"
            f"  <cwd>{cwd}</cwd>\n"
            f"  <approval_policy>{approval_policy}</approval_policy>\n"
            f"  <sandbox_mode>{sandbox_mode}</sandbox_mode>\n"
            f"  <network_access>{network_access}</network_access>\n"
            f"  <shell>{shell}</shell>\n"
            "</environment_context>"
            )

        return {"type": "message", "role": "user", "content": content}

    async def run(self, user_message: str) -> AsyncGenerator[Dict[str, Any], None]:

        self.turn_index = 0
        yield {"type": "user_message", "data": {"message": user_message, "turn": self.turn_index}}

        model_name = self.config.active_model.model or "gpt-5-codex"
        provider = self.config.active_model.provider or "openai"

        session_stats.record_task_start(self.type)

        max_tokens = TokenLimits.get_limit("openai", model_name)
        if self.cli_console:
            self.cli_console.set_max_context_tokens(max_tokens)

        self.trajectory_recorder.start_recording(
            task=user_message, provider=provider, model=model_name, max_steps=self.turn_cnt_max
        )
        self.history.add_message(role="user", content=user_message)
        env_msg = self.build_environment_context(cwd=os.getcwd(),shell=os.environ.get("SHELL", "bash"))
        self.history.add_item(env_msg)

        while self.turn_index < self.turn_cnt_max:
            messages = self.history.to_responses_input()
            params = {"model": model_name, "api": self.config.active_model.wire_api, "tools" : self.tools}

            self.current_task = None
            for m in reversed(messages):
                if m.get("role") == "user":
                    self.current_task = m.get("content")
                    break

            stage = self._responses_event_process(messages= messages, params=params)

            async for ev in stage:
                yield ev

    def _build_system_prompt(self) -> str:
        import inspect
        agent_dir = Path(inspect.getfile(self.__class__)).parent
        codex_md = agent_dir / "gpt_5_codex_prompt.md"
        if not codex_md.exists():
            raise FileNotFoundError(f"Missing system prompt file '{codex_md}'")
        return codex_md.read_text(encoding="utf-8")

    def record_turn_messages(self, messages: List[Dict[str, Any]], responses) -> None:
        """记录每轮的消息到轨迹记录器"""
        #1. 转换messages格式, pydantic -> dict
        converted_messages = []
        llm_msg = None
        for msg in messages:
            if isinstance(msg, BaseModel):
                if msg.type == "function_call" or msg.type == "custom_tool_call":
                    tool_call = ToolCall(
                        call_id = msg.call_id,
                        name = msg.name,
                        arguments = json.loads(msg.arguments) if msg.type == "function_call" else msg.input,
                        type = msg.type,
                    )
                data = msg.model_dump(exclude_none=True)
                llm_msg = LLMMessage(
                        role = data.get("role", ""),
                        content = data.get("content"),
                        tool_calls = [tool_call],
                        tool_call_id = data.get("tool_call_id"),
                        )
            elif isinstance(msg, dict):
                llm_msg = LLMMessage(
                        role = msg.get("role", msg.get("type")),
                        content = msg.get("content", msg.get("name")),
                        tool_calls = None,
                        tool_call_id = None,
                        )
            converted_messages.append(llm_msg)

        #2. 转换responses格式
        if isinstance(responses, BaseModel):
            from pywen.utils.llm_basics import LLMResponse
            tool_calls = []
            for out in responses.output:
                if out.type == "function_call" or out.type == "custom_tool_call":
                    tool_call = ToolCall(
                        call_id = out.call_id,
                        name = out.name,
                        arguments = json.loads(out.arguments) if out.type == "function_call" else out.input,
                        type = out.type,
                    )
                    tool_calls.append(tool_call)
 
            resp = LLMResponse(
                    content = responses.output_text,
                    tool_calls = tool_calls,
                    usage = responses.usage,
                    model = self.config.active_model.model,
                    finish_reason = "completed",
                    )

        self.trajectory_recorder.record_llm_interaction(
                messages = converted_messages,
                response = resp,
                provider = self.config.active_model.provider or "openai",
                model = self.config.active_model.model or "gpt-5-codex",
                tools = self.tools,
                current_task = self.current_task,
                agent_name = self.type,
        )

    async def _responses_event_process(self, messages, params) -> AsyncGenerator[Dict[str, Any], None]:
        """在这里处理LLM的事件，转换为agent事件流"""
        async for evt in self.llm_client.astream_response(messages, **params):
            #print(evt)
            if evt.type == "created":
                yield {"type": "llm_stream_start", "data": {"message": "LLM response stream started"}}

            elif evt.type == "output_text.delta":
                yield {"type": "llm_chunk", "data": {"content": evt.data}}
    
            elif evt.type == "tool_call.ready":
                if evt.data is None: continue
                item = evt.data
                self.history.add_item(item)
                if item.type == "function_call":
                    tc = ToolCall(item.call_id, item.name, json.loads(item.arguments), item.type)
                elif item.type == "custom_tool_call":
                    tc = ToolCall(item.call_id, item.name, item.input, item.type)
                else:
                    continue

                async for tool_event in self._process_one_tool_call(tc):
                    yield tool_event

            elif evt.type == "reasoning_summary_text.delta":
                payload = {"reasoning": evt.data, "turn": self.turn_index}
                yield {"type": "waiting_for_user", "data": payload}

            elif evt.type == "reasoning_text.delta":
                continue

            elif evt.type == "completed":
                #一轮结束
                self.record_turn_messages(messages, evt.data)
                self.turn_index += 1
                if evt.data and self.cli_console:
                    total_tokens = evt.data.usage.total_tokens
                    self.cli_console.update_token_usage(total_tokens)

                has_tool_call = False
                for out in evt.data.output:
                    if out.type == "function_call" or out.type == "custom_tool_call":
                        has_tool_call = True
                        break
                if has_tool_call:
                    yield {"type": "turn_complete", "data": {"status": "completed"}}
                else:
                    yield {"type": "task_complete", "data": {"status": "completed"}}


            elif evt.type == "error":
                yield {"type": "error", "data": {"error": str(evt.data)}}



    async def _process_one_tool_call(self, tool_call :ToolCall) -> AsyncGenerator[Dict[str, Any], None]:
        tool = get_tool(tool_call.name)
        if not tool:
            return
        if not self.cli_console:
            return
        #格式不一致，需要特殊处理
        confirm_tool_call = tool_call
        if isinstance(tool_call.arguments, Mapping):
            confirm_tool_call.arguments = dict(tool_call.arguments)
        elif isinstance(tool_call.arguments, str) and tool_call.name == "apply_patch":
            confirm_tool_call.arguments = {"input": tool_call.arguments}

        confirmed = await self.cli_console.confirm_tool_call(confirm_tool_call, tool)
        if not confirmed:
            self.history.add_message(role="assistant", content=f"Tool call '{tool_call.name}' was rejected by the user.")
            payload = {"call_id": tool_call.call_id, 
                        "name": tool_call.name, 
                        "result": "Tool execution rejected by user",
                        "success":False,
                        "error": "Tool execution rejuected by user",
                        }
            yield {"type": "tool_result", "data": payload}
            return
        try:
            result = await tool.execute(**confirm_tool_call.arguments)
            payload = {"call_id": tool_call.call_id, 
                       "name": tool_call.name, 
                       "result": result.result,
                       "success": result.success, 
                       "error": result.error, 
                       "arguments": tool_call.arguments
                    }
            tool_output_item = {
                    "type": "function_call_output", 
                    "call_id": tool_call.call_id, 
                    "output": json.dumps({
                            "result": result.result,
                         })
                    }
            self.history.add_item(tool_output_item)
            yield {"type": "tool_result", "data": payload}
        except Exception as e:
            print("Tool execution error: ", str(e))
            error_msg = f"Tool execution failed: {str(e)}"
            tool_output_item = {"type": "function_call_output", "call_id": tool_call.call_id, "output": "tool failed"}
            self.history.add_item(tool_output_item)
            yield {"type": "tool_error", "data": {"call_id": tool_call.call_id, "name": tool_call.name, "error": error_msg}}

