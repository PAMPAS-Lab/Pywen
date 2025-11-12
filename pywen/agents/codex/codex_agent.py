import json,os,uuid
from pathlib import Path
from typing import Dict, List, Union, Literal, Any, AsyncGenerator
from pydantic import BaseModel
from pywen.agents.base_agent import BaseAgent
from pywen.llm.llm_client import LLMClient, LLMConfig 
from pywen.utils.tool_basics import ToolCall
from pywen.utils.token_limits import TokenLimits, ModelProvider
from pywen.core.session_stats import session_stats

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
        self.llmconfig = LLMConfig(
            provider=config.model_config.provider.value,
            api_key=config.model_config.api_key,
            base_url=config.model_config.base_url,
            model= config.model_config.model or "gpt-5-codex",
            turn_cnt_max = 5,
            wire_api="responses",
        )
        self.llm_client = LLMClient(self.llmconfig)
        session_stats.set_current_agent(self.type)
        self.turn_cnt_max = self.llmconfig.turn_cnt_max
        self.max_iterations = config.max_iterations
        self.turn_index = 0
        self.history: History = History(system_prompt= self._build_system_prompt())
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

        model_name = self.llmconfig.model
        provider = self.llmconfig.provider
        session_stats.record_task_start(self.type)

        max_tokens = TokenLimits.get_limit(ModelProvider.OPENAI, model_name)
        if self.cli_console:
            self.cli_console.set_max_context_tokens(max_tokens)

        self.trajectory_recorder.start_recording(
            task=user_message, provider=provider, model=model_name, max_steps=self.max_iterations
        )
        self.history.add_message(role="user", content=user_message)
        env_msg = self.build_environment_context(cwd=os.getcwd(),shell=os.environ.get("SHELL", "bash"))
        self.history.add_item(env_msg)
        conversation_id = await self.llm_client.aconversations_create()
        while self.turn_index < self.turn_cnt_max:
            messages = self.history.to_responses_input()
            print(f"----当前轮次:  {self.turn_index + 1} -------")
            print(messages)
            for msg in messages:
                self.trajectory_recorder.record_input(msg)
            params = {"conversation": conversation_id, "model": model_name, "api":"responses", "tools" : self.tools}
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

    async def _responses_event_process(self, messages, params) -> AsyncGenerator[Dict[str, Any], None]:
        """在这里处理LLM的事件，转换为agent事件流"""

        async for evt in self.llm_client.astream_response(messages, **params):
            for d in evt.data if isinstance(evt.data, list) else [evt.data]:
                if isinstance(d, dict):
                    self.trajectory_recorder.record_response(d)
                elif isinstance(d, BaseModel):
                    self.trajectory_recorder.record_response(d.model_dump(exclude_none=True))
            if evt.type == "created":
                yield {"type": "llm_stream_start", "data": {"message": "LLM response stream started"}}

            elif evt.type == "output_text.delta":
                yield {"type": "llm_chunk", "data": {"content": evt.data}}
    
            elif evt.type == "tool_call.ready":
                #TODO. 判断是否可能有多个tool call
                if evt.data is None: continue
                tool_args = {} 
                if evt.data.get('type') == "custom_tool_call":
                    #TODO.这里的args可能不是patch
                    tool_args = {
                            "patch" : evt.data.get('args'),
                            }
                    custom_tool_call = {
                            "call_id" : evt.data.get("call_id"),
                            "input" : evt.data.get('args'),
                            "name" : evt.data.get('name'),
                            "type" : "custom_tool_call",
                            "id" : evt.data.get('id'),
                            "status" : evt.data.get('status'),
                            }
                    self.history.add_item(custom_tool_call)
                elif evt.data.get('type') == "function_call":
                    try:
                        tool_args = json.loads(evt.data.get('args'))
                    except:
                        tool_args = {"input": evt.data.get('args')}

                    function_call = {
                            "call_id" : evt.data.get("call_id"),
                            "arguments" : evt.data.get('args'),
                            "name" : evt.data.get('name'),
                            "type" : "function_call",
                            "id" : evt.data.get('id'),
                            "status" : evt.data.get('status'),
                            }
                    self.history.add_item(function_call)
                else:
                    #reasoning
                    reasoning_call = {
                            "id" : evt.data.get("id"),
                            "type" : "reasoning",
                            "status" : evt.data.get('status'),
                            "summary" : evt.data.get('summary'),
                            "encrypted_content" : evt.data.get('encrypted_content'),
                            }
                    self.history.add_item(evt.data)

                tc = ToolCall(
                        call_id = evt.data.get("call_id"), 
                        name = evt.data.get('name'), 
                        arguments = tool_args,
                        type = evt.data.get('kind'),
                    )


                async for tool_event in self._process_one_tool_call(tc):
                    yield tool_event

            elif evt.type == "reasoning_summary_text.delta":
                payload = {"reasoning": evt.data, "turn": self.turn_index}
                yield {"type": "waiting_for_user", "data": payload}

            elif evt.type == "reasoning_text.delta":
                continue

            elif evt.type == "completed":
                #一轮结束
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


    async def _process_one_tool_call(self, tool_call) -> AsyncGenerator[Dict[str, Any], None]:
        tool = self.tool_registry.get_tool(tool_call.name)
        if not tool:
            return
        if not self.cli_console:
            return
        confirmed = await self.cli_console.confirm_tool_call(tool_call, tool)
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
            results = await self.tool_executor.execute_tools([tool_call], self.type)
            result = results[0]
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
                    "output": json.dumps(
                        {
                            "arguments": tool_call.arguments,
                            "result": result.result,
                         }, 
                     ensure_ascii=False
                    )
            }
            self.history.add_item(tool_output_item)
            yield {"type": "tool_result", "data": payload}
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            tool_output_item = {"type": "function_call_output", "call_id": tool_call.call_id, "output": "tool failed"}
            self.history.add_item(tool_output_item)
            yield {"type": "tool_error", "data": {"call_id": tool_call.call_id, "name": tool_call.name, "error": error_msg}}

