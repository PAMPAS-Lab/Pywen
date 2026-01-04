import json,os
import inspect
from pathlib import Path
from typing import Dict, List, Mapping, Literal, Any, AsyncGenerator
from typing_extensions import override
from pydantic import BaseModel
from pywen.agents.base_agent import BaseAgent
from pywen.agents.agent_events import AgentEvent 
from pywen.llm.llm_basics import ToolCall, LLMMessage
from pywen.llm.llm_events import LLM_Events 
from pywen.config.token_limits import TokenLimits 
from pywen.utils.session_stats import session_stats
from pywen.tools.tool_manager import ToolManager
from pywen.memory.memory_monitor import MemoryMonitor

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

    def to_llm_messages(self) -> List[LLMMessage]:
        llm_messages = []
        for msg in self._items[1:]:  #跳过system
            role, content, tool_calls, tool_call_id = "", "", None, None
            if msg.get("type") in {"function_call", "custom_tool_call", "function"}:
                role = "assistant"
                arguments = json.loads(msg.get("arguments", "")) if msg.get("type") in ["function_call", "function"] else msg.get("input")
                content = ""
                tool_call = ToolCall(
                    call_id = msg.get("call_id", ""),
                    name = msg.get("name", ""),
                    arguments = arguments,
                    type = msg.get("type"),
                )
                tool_calls = [tool_call]
                tool_call_id = msg.get("call_id")
            elif msg.get('type') == "message":
                role = msg.get("role", "user")
                if role in ["user", "system"]: 
                    content = msg.get("content", "")
                elif role == "assistant":
                    ctx = msg.get("content", {})
                    for c in ctx:
                        if c.get("type") == "output_text":
                            content += c.get("text", "")
            else:
                continue

            llm_msg = LLMMessage(
                role = role,
                content = content,
                tool_calls = tool_calls,
                tool_call_id = tool_call_id,
            )
            llm_messages.append(llm_msg)
        return llm_messages

class CodexAgent(BaseAgent):
    def __init__(self, config_mgr, cli, tool_mgr:ToolManager):
        super().__init__(config_mgr, cli, tool_mgr)
        self.type = "CodexAgent"
        session_stats.set_current_agent(self.type)
        self.turn_cnt_max = self.config_mgr.get_app_config().max_turns
        self.turn_index = 0
        self.system_prompt = self._build_system_prompt()
        self.history: History = History(system_prompt= self.system_prompt)
        self.tools = [tool.build("codex") for tool in self.tool_mgr.list_for_provider("codex")]
        self.current_task = None

    def get_enabled_tools(self) -> List[str]:
        return ['shell_tool', 'update_plan', 'apply_patch',]

    def build_environment_context(self, cwd: str, approval_policy: str = "on-request", 
            sandbox_mode: str = "workspace-write", network_access: str = "restricted", shell: str = "zsh", ) -> str:
        content = (
            "<environment_context>\n"
            f"  <cwd>{cwd}</cwd>\n"
            f"  <approval_policy>{approval_policy}</approval_policy>\n"
            f"  <sandbox_mode>{sandbox_mode}</sandbox_mode>\n"
            f"  <network_access>{network_access}</network_access>\n"
            f"  <shell>{shell}</shell>\n"
            "</environment_context>"
            )

        return content

    @override
    async def context_compact(self, mem: MemoryMonitor, turn:int) -> None:
        history = self.history.to_llm_messages()
        tokens_used = sum(self.approx_token_count(m.content or "") for m in history)
        used, summary = await mem.run_monitored(self.llm_client, self.cli, history, tokens_used, turn)
        if used > 0 and summary:
            self.conversation_history = [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(role="user", content=self.build_environment_context(cwd=os.getcwd(),shell=os.environ.get("SHELL", "bash"))),
                    LLMMessage(role="user", content=summary)
            ]
            self.cli.set_current_tokens(used)
 
    async def run(self, user_message: str) -> AsyncGenerator[AgentEvent, None]:

        self.turn_index = 0
        agent_config = self.config_mgr.get_active_agent()
        yield AgentEvent.user_message(user_message, self.turn_index)

        model_name = self.config_mgr.get_active_model_name() or "gpt-5-codex"
        max_tokens = TokenLimits.get_limit("openai", model_name)
        self.cli.set_max_context_tokens(max_tokens)
        provider = agent_config.provider or "openai"

        session_stats.record_task_start(self.type)

        self.trajectory_recorder.start_recording(
            task=user_message, provider=provider, model=model_name, max_steps=self.turn_cnt_max
        )
        env_msg = self.build_environment_context(cwd=os.getcwd(),shell=os.environ.get("SHELL", "bash"))
        project_msg = self.config_mgr.get_project_prompt()
        skills_msg = self.config_mgr.get_skills_prompt()
        self.history.add_message(role="user", content=project_msg)
        self.history.add_message(role="user", content=env_msg)
        self.history.add_message(role="user", content=skills_msg)
        self.history.add_message(role="user", content=user_message)

        while self.turn_index < self.turn_cnt_max:
            messages:List[HistoryItem] = self.history.to_responses_input()
            params = {"model": model_name, "api": agent_config.wire_api, "tools" : self.tools}
            self.current_task = None
            for m in reversed(messages):
                if m.get("role") == "user":
                    self.current_task = m.get("content")
                    break

            stage = self._responses_event_process(messages= messages, params=params)
            async for ev in stage:
                yield ev

    def _build_system_prompt(self) -> str:
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
        model_name = self.config_mgr.get_active_model_name() or "gpt-5-codex"
        for msg in messages:
            if isinstance(msg, BaseModel):
                if msg.type in {"function_call", "custom_tool_call", "function"}:
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
                        role = msg.get("role") or msg.get("type") or "user",
                        content = msg.get("content", msg.get("name")),
                        tool_calls = None,
                        tool_call_id = None,
                        )
            converted_messages.append(llm_msg)

        #2. 转换responses格式
        if isinstance(responses, BaseModel):
            from pywen.llm.llm_basics import LLMResponse
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
                    model = model_name,
                    finish_reason = "completed",
                    )

        self.trajectory_recorder.record_llm_interaction(
                messages = converted_messages,
                response = resp,
                provider = self.config_mgr.get_active_agent().provider or "openai",
                model = model_name,
                tools = self.tools,
                current_task = self.current_task,
                agent_name = self.type,
        )

    async def _responses_event_process(self, messages:List[HistoryItem], params) -> AsyncGenerator[AgentEvent, None]:
        """在这里处理LLM的事件，转换为agent事件流"""

        history = self.history.to_llm_messages()
        tokens_used = sum(self.approx_token_count(m.content or "") for m in history)
        self.cli.set_current_tokens(tokens_used)
        async for event in self.llm_client.astream_response(messages, **params):
            if event.type == LLM_Events.REQUEST_STARTED:
                yield AgentEvent.llm_stream_start()

            elif event.type == LLM_Events.ASSISTANT_DELTA:
                yield AgentEvent.text_delta(str(event.data))
    
            elif event.type == LLM_Events.TOOL_CALL_READY:
                if event.data is None: continue
                item = event.data
                self.history.add_item(item)
                if item.type == "function_call" or item.type == "function":
                    tc = ToolCall(item.call_id, item.name, json.loads(item.arguments), item.type)
                elif item.type == "custom_tool_call":
                    tc = ToolCall(item.call_id, item.name, item.input, item.type)
                else:
                    continue
                async for tool_event in self._process_one_tool_call(tc):
                    yield tool_event

            elif event.type == LLM_Events.REASONING_DELTA:
                continue

            elif event.type == LLM_Events.RESPONSE_FINISHED:
                #一轮结束
                self.record_turn_messages(messages, event.data)
                self.turn_index += 1
                has_tool_call = False
                for out in event.data.output:
                    if out.type in{"function_call", "custom_tool_call", "function"}:
                        has_tool_call = True
                        break
                if has_tool_call:
                    yield AgentEvent.turn_complete()
                else:
                    yield AgentEvent.task_complete("completed")
            elif event.type == LLM_Events.TOKEN_USAGE:
                usage = event.data or {}
                total = usage.get("total_tokens", 0)
                yield AgentEvent.turn_token_usage(total)
            elif event.type == "error":
                yield AgentEvent.error(str(event.data))

    async def _process_one_tool_call(self, tool_call :ToolCall) -> AsyncGenerator[AgentEvent, None]:
        name = tool_call.name
        tool = self.tool_mgr.get_tool(name)
        if not tool:
            return
        call_id = tool_call.call_id
        arguments = {}
        if isinstance(tool_call.arguments, Mapping):
            arguments = dict(tool_call.arguments)
        elif isinstance(tool_call.arguments, str) and tool_call.name == "apply_patch":
            arguments = {"input": tool_call.arguments}

        yield AgentEvent.tool_call(call_id, name, arguments)
        try:
            is_success, result = await self.tool_mgr.execute(name, arguments, tool)
            if not is_success:
                self.history.add_message(role="assistant", content= result)
                yield AgentEvent.tool_result(call_id, name, result, False, arguments)
                return
            item = {"type": "function_call_output", "call_id": call_id, "output": json.dumps({"result": result,}) }
            self.history.add_item(item)
            yield AgentEvent.tool_result(call_id, name, result, True, arguments)
        except Exception as e:
            item = {"type": "function_call_output", "call_id": call_id, "output": "tool failed"}
            self.history.add_item(item)
            error_msg = f"Tool execution failed: {str(e)}"
            yield AgentEvent.tool_result(call_id, name, error_msg, False, arguments)

