"""Pywen Agent implementation with streaming logic."""
import os,subprocess, json
import platform, shutil
from pathlib import Path
from typing import Dict, List, Any, AsyncGenerator,Mapping
from pywen.agents.base_agent import BaseAgent
from pywen.agents.agent_events import AgentEvent 
from pywen.llm.llm_basics import LLMMessage
from pywen.llm.llm_events import LLM_Events
from pywen.config.token_limits import TokenLimits
from pywen.utils.session_stats import session_stats
from pywen.llm.llm_basics import LLMResponse, ToolCall
from .prompts import (
    SYSTEM_PROMPT,
    TOOL_PROMPT_SUFFIX,
    RUNTIME_ENV_LINUX_PROMPT,
    RUNTIME_ENV_MACOS_PROMPT,
    RUNTIME_ENV_WINDOWS_PROMPT,
    STYLE_PROMPT,
    BASE_PROMPT_DEFAULT,
    SANDBOX_MACOS_SEATBELT_PROMPT,
    SANBOX_DEFAULT,
    SANBOX_OUTSIDE,
    GIT_INFO_BLOCK,
)

class PywenAgent(BaseAgent):
    """Pywen Agent with streaming iterative tool calling logic."""
    
    def __init__(self, config_mgr, cli, tool_mgr):
        super().__init__(config_mgr, cli, tool_mgr)
        self.type = "PywenAgent"
        session_stats.set_current_agent(self.type)
        self.current_turn_index = 0
        self.max_turns = self.config_mgr.get_app_config().max_turns
        self.system_prompt = self.get_core_system_prompt()
        self.conversation_history = self._update_system_prompt(self.system_prompt)
        self.file_metrics = {} 
    
    async def run(self, user_message: str) -> AsyncGenerator[AgentEvent, None]:
        """Run agent with streaming output and task continuation."""
        model_name = self.config_mgr.get_active_model_name() or ""
        max_tokens = TokenLimits.get_limit("qwen", model_name)
        self.cli.set_max_context_tokens(max_tokens)
        await self.setup_tools_mcp()
        self.current_turn_index = 0
        session_stats.record_task_start(self.type)
        self.trajectory_recorder.start_recording(
            task=user_message,
            provider=self.config_mgr.get_active_agent().provider or "",
            model= model_name,
            max_steps=self.max_turns
        )
        yield AgentEvent.user_message(user_message, self.current_turn_index)

        self.conversation_history.append(LLMMessage(role="user", content=user_message))

        while self.current_turn_index < self.max_turns:
            async for event in self._process_turn_stream():
                yield event

    async def _process_turn_stream(self) -> AsyncGenerator[AgentEvent, None]:
        messages = [self._convert_single_message(msg) for msg in self.conversation_history]
        trajectory_msg = self.conversation_history.copy()
        tools = [tool.build("pywen") for tool in self.tool_mgr.list_for_provider("pywen")]
        completed_resp : LLMResponse = LLMResponse(content = "")

        tokens_used = sum(self.approx_token_count(m.content or "") for m in self.conversation_history)
        self.cli.set_current_tokens(tokens_used)
        async for event in self.llm_client.astream_response(messages= messages, tools= tools, api = "chat"):
            if event.type == LLM_Events.REQUEST_STARTED:
                yield AgentEvent.llm_stream_start()
            elif event.type == LLM_Events.ASSISTANT_DELTA:
                yield AgentEvent.text_delta(str(event.data))
            elif event.type == LLM_Events.TOOL_CALL_DELTA:
                tc_data = event.data
                if tc_data is None:
                    continue
            elif event.type == LLM_Events.TOOL_CALL_READY:
                # 返回内容是tool_calls 字典列表
                # 1. 填充assistant LLMMessage
                tool_calls = event.data or {}
                tc_list = [ToolCall.from_raw(tc) for tc in tool_calls]
                assistant_msg = LLMMessage(
                    role="assistant",
                    tool_calls = tc_list,
                    content = "",
                )
                self.conversation_history.append(assistant_msg)
                # 2. 执行工具调用，拿到结果，填充tool LLMMessage
                async for tc_event in self._process_tool_calls(tc_list):
                    yield tc_event
            elif event.type == LLM_Events.TOKEN_USAGE:
                # 更新 token 使用统计
                usage = event.data or {}
                total = usage.get("total_tokens", 0)
                yield AgentEvent.turn_token_usage(total)
            elif event.type == LLM_Events.RESPONSE_FINISHED:
                self.current_turn_index += 1
                if not event.data:
                    continue
               # 处理结束状态
                finish_reason = event.data.get("finish_reason")
                completed_resp = LLMResponse.from_raw(event.data or {})
                self.trajectory_recorder.record_llm_interaction(
                    messages= trajectory_msg,
                    response= completed_resp, 
                    provider=self.config_mgr.get_active_agent().provider or "",
                    model=self.config_mgr.get_active_model_name() or "",
                    tools=tools,
                    agent_name=self.type,
                )

                if finish_reason and finish_reason != "tool_calls":
                    yield AgentEvent.task_complete(finish_reason)

    def _convert_single_message(self, msg: LLMMessage) -> Dict[str, Any]:
        role = msg.role
        data: Dict[str, Any] = {"role": role}
        if role in ("system", "user"):
            data["content"] = msg.content or ""
            return data
    
        if role == "assistant":
            if msg.content is not None:
                data["content"] = msg.content
            if msg.tool_calls:
                converted_tool_calls = []
                for tc in msg.tool_calls:
                    converted_tool_calls.append({
                        "id": tc.call_id,
                        "type": tc.type or "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments or {}),
                        },
                    })
                data["tool_calls"] = converted_tool_calls
                return data

        if role == "tool":
            if not msg.tool_call_id:
                raise ValueError("Tool message must have tool_call_id")
            data["tool_call_id"] = msg.tool_call_id
            data["content"] = msg.content
            return data
    
        raise ValueError(f"Unsupported role for OpenAI messages: {role!r}")
 
    async def _process_tool_calls(self, tool_calls : List[ToolCall]) -> AsyncGenerator[AgentEvent, None]:
        # 2. 执行工具调用，拿到结果，填充tool LLMMessage
        for tc in tool_calls:
            tool = self.tool_mgr.get_tool(tc.name)
            if not tool:
                continue
            name = tc.name
            call_id = tc.call_id
            arguments = {}
            if isinstance(tc.arguments, Mapping):
                arguments = dict(tc.arguments)
            elif isinstance(tc.arguments, str) and tc.name == "apply_patch":
                arguments = {"input": tc.arguments}
           
            yield AgentEvent.tool_call(call_id, name, arguments)
            try:
                is_success, result = await self.tool_mgr.execute(name, arguments, tool)
                if not is_success:
                    msg = LLMMessage(role="tool", content= str(result), tool_call_id= call_id)
                    self.conversation_history.append(msg)
                    yield AgentEvent.tool_result(call_id, name, result, False, arguments)
                    continue
                yield AgentEvent.tool_result(call_id, name, result, True, arguments)
                content = result if isinstance(result, str) else json.dumps(result)
                tool_msg = LLMMessage(role="tool", content= content, tool_call_id=tc.call_id)
                self.conversation_history.append(tool_msg)
            except Exception as e:
                error_msg = f"Tool execution failed: {str(e)}"
                tool_msg = LLMMessage(role="tool", content= error_msg, tool_call_id=tc.call_id)
                self.conversation_history.append(tool_msg)
                yield AgentEvent.tool_result(call_id, name, error_msg, False, arguments)

    def _build_runtime_env_prompt(self) -> str:
        sys_name = platform.system()
        release = platform.release()
        python = platform.python_version()
    
        if sys_name == "Windows":
            comspec = os.environ.get("COMSPEC", "")
            ps = shutil.which("powershell") or shutil.which("pwsh")
            shell_hint = "PowerShell preferred" if ps else "cmd.exe"
    
            return RUNTIME_ENV_WINDOWS_PROMPT.format(
                release=release,
                python=python,
                shell_hint=shell_hint,
                comspec=comspec,
            )
    
        if sys_name == "Darwin":
            return RUNTIME_ENV_MACOS_PROMPT.format(
                release=release,
                python=python,
            )
    
        # Linux / other Unix
        return RUNTIME_ENV_LINUX_PROMPT.format(
            release=release,
            python=python,
        )

    def _build_pywen_md_prompt(self) -> str:
        filename = "PYWEN.md"
        parts: list[str] = []
        current_dir = Path.cwd().resolve()
        max_hops = 512
        hops = 0
        while True:
            md_path = current_dir / filename
            if md_path.is_file():
                try:
                    content = md_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = md_path.read_text(encoding="utf-8", errors="replace")
                parts.append(f"Contents of {md_path}:\n\n{content}")

            parent = current_dir.parent
            if parent == current_dir:
                break
            current_dir = parent
            hops += 1
            if hops >= max_hops:
                break
        if not parts:
            return ""
        parts.reverse()

        return f"{STYLE_PROMPT}\n\n" + "\n\n".join(parts)

    def _update_system_prompt(self, system_prompt: str) -> List[LLMMessage]:
        cwd_prompt = (
            f"Please note that the user launched Pywen under the path {Path.cwd()}.\n"
            "All subsequent file-creation, file-writing, file-reading, and similar "
            "operations should be performed within this directory."
        )
        env_prompt = self._build_runtime_env_prompt()
        style_prompt = self._build_pywen_md_prompt()
        prompt = system_prompt.rstrip() \
                + "\n\n" + style_prompt \
                + "\n\n" + env_prompt \
                + "\n\n" + self.skills_prompt \
                + "\n\n" + cwd_prompt
        system_message = LLMMessage(role="system", content= prompt)
        return [system_message]

    def _build_system_prompt(self) -> str:
        """Build system prompt with tool descriptions."""
        available_tools = self.tool_mgr.list_for_provider("pywen")
        system_prompt = SYSTEM_PROMPT 
        for tool in available_tools:
            system_prompt += f"- **{tool.name}**: {tool.description}\n"
            params = tool.parameter_schema.get('properties', {})
            if not params:
                continue
            param_list = ", ".join(params.keys())
            system_prompt += f"  Parameters: {param_list}\n"
        
        system_prompt += TOOL_PROMPT_SUFFIX 
        return system_prompt.strip()

    def get_core_system_prompt(self,user_memory: str = "") -> str:
        PYWEN_CONFIG_DIR = Path.home() / ".pywen"
        system_md_enabled = False
        system_md_path = (PYWEN_CONFIG_DIR / "system.md").resolve()
        system_md_var = os.environ.get("PYWEN_SYSTEM_MD", "").lower()
        if system_md_var and system_md_var not in ["0", "false"]:
            system_md_enabled = True
            if system_md_var not in ["1", "true"]:
                system_md_path = Path(system_md_var).resolve()
            if not system_md_path.exists():
                raise FileNotFoundError(f"Missing system prompt file '{system_md_path}'")

        def is_git_repository(path: Path) -> bool:
            """Check if the given path is inside a Git repository."""
            try:
                subprocess.run(
                    ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                return True
            except subprocess.CalledProcessError:
                return False

        def sandbox_info() -> str:
            if os.environ.get("SANDBOX") == "sandbox-exec":
                return SANDBOX_MACOS_SEATBELT_PROMPT 
            elif os.environ.get("SANDBOX"):
                return SANBOX_DEFAULT 
            else:
                return SANBOX_OUTSIDE 

        def git_info_block() -> str:
            if not is_git_repository(Path.cwd()):
                return "" 
            return  GIT_INFO_BLOCK

        base_prompt = system_md_path.read_text() if system_md_enabled else BASE_PROMPT_DEFAULT.strip()

        write_system_md_var = os.environ.get("PYWEN_WRITE_SYSTEM_MD", "").lower()
        if write_system_md_var and write_system_md_var not in ["0", "false"]:
            target_path = (
                system_md_path
                if write_system_md_var in ["1", "true"]
                else Path(write_system_md_var).resolve()
            )
            target_path.write_text(base_prompt)

        base_prompt += "\n" + sandbox_info()
        base_prompt += "\n" + git_info_block()

        if user_memory.strip():
            base_prompt += f"\n\n---\n\n{user_memory.strip()}"

        return base_prompt
