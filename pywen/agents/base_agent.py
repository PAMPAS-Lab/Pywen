import re
import asyncio
from typing import AsyncGenerator
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from pywen.config.manager import ConfigManager
from pywen.llm.llm_client import LLMClient 
from pywen.utils.trajectory_recorder import TrajectoryRecorder
from pywen.llm.llm_basics import LLMMessage
from pywen.tools.tool_manager import ToolManager
from pywen.tools.mcp_tool import sync_mcp_servers
from pywen.agents.agent_events import AgentEvent 
from pywen.memory.memory_monitor import MemoryMonitor
from pywen.cli.cli_console import CLIConsole

class BaseAgent(ABC):
    def __init__(self, config_mgr: ConfigManager, cli:CLIConsole, tool_mgr :ToolManager) -> None:
        self.type = "BaseAgent"
        self.conversation_history: List[LLMMessage] = []
        self.trajectory_recorder = TrajectoryRecorder()
        self._closed = False 
        self._mcp_mgr = None
        self._mcp_init_lock = asyncio.Lock()
        self.config_mgr = config_mgr
        self.cli = cli
        self.tool_mgr = tool_mgr
        self.llm_client = LLMClient(self.config_mgr.get_active_agent())
        self.skills_prompt = self.config_mgr.get_skills_prompt()

    async def setup_tools_mcp(self):
        """Setup tools based on agent configuration."""
        await self._ensure_mcp_synced()
    
    def get_tool_configs(self) -> Dict[str, Dict[str, Any]]:
        """Return tool-specific configurations. Override if needed."""
        return {}

    @abstractmethod
    def run(self, user_message: str) -> AsyncGenerator[AgentEvent, None]:
        """Run the agent - must be implemented by subclasses."""
        pass

    async def context_compact(self, mem: MemoryMonitor, turn:int) -> None:
        history = self.conversation_history
        tokens_used = sum(self.approx_token_count(m.content or "") for m in history)
        used, summary = await mem.run_monitored(self.llm_client, self.cli, history, tokens_used, turn)
        if used > 0 and summary:
            self.conversation_history = [LLMMessage(role="user", content=summary)]
            self.cli.set_current_tokens(used)

    def _build_system_prompt(self) -> str:
        """Build system prompt with tool descriptions."""
        return "" 

    async def _ensure_mcp_synced(self):
        """
        依据当前配置将 MCP servers 同步为本地工具。
        """
        async with self._mcp_init_lock:
            if self._mcp_mgr is not None:
                return
            try:
                mcp_mgr, _ = await sync_mcp_servers(cfg_mgr=self.config_mgr,)
                self._mcp_mgr = mcp_mgr
            except Exception:
                self._mcp_mgr = None
                return

    def approx_token_count(self, text: str) -> int:
        if not text:
            return 0
    
        words = re.findall(r"\S+", text)
        word_count = len(words)
        punct_count = len(re.findall(r"[,\.\!\?\:\;\(\)\[\]\{\}\-]", text))
        special_char_count = len(re.findall(r"[^A-Za-z0-9\s]", text))
    
        length_factor = len(text) // 20 
    
        estimate = (
            word_count
            + punct_count
            + special_char_count // 2
            + length_factor
        )
        return max(estimate, word_count)
    
    async def aclose(self):
        if self._closed:
            return 
        self._closed = True 
        if self._mcp_mgr:
            try:
                await self._mcp_mgr.close()
            finally:
                self._mcp_mgr = None

    async def __aenter__(self):
        await self._ensure_mcp_synced()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

