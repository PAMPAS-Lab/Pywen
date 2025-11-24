import asyncio
import fnmatch
from typing import Callable, Iterable, Optional, AsyncGenerator
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from pywen.config.config import AppConfig, MCPConfig
from pywen.ui.cli_console import CLIConsole
from pywen.core.trajectory_recorder import TrajectoryRecorder
from pywen.utils.llm_basics import LLMMessage
from pywen.tools.mcp_tool import MCPServerManager, sync_mcp_server_tools_into_registry
from pywen.hooks.manager import HookManager
from pywen.core.tool_registry2 import list_tools_for_provider

class BaseAgent(ABC):
    def __init__(self, config: AppConfig, hook_mgr:HookManager, cli_console: Optional[CLIConsole] =None):
        self.config = config
        self.cli_console = cli_console
        self.type = "BaseAgent"
        self.conversation_history: List[LLMMessage] = []
        self.trajectory_recorder = TrajectoryRecorder()
        self._closed = False 
        self._mcp_mgr = None
        self._mcp_init_lock = asyncio.Lock()

        self.hook_mgr = hook_mgr

    async def setup_tools_mcp(self):
        """Setup tools based on agent configuration."""
        
        await self._ensure_mcp_synced()
    
    def get_tool_configs(self) -> Dict[str, Dict[str, Any]]:
        """Return tool-specific configurations. Override if needed."""
        return {}
    
    def set_cli_console(self, console):
        """Set the CLI console for progress updates."""
        self.cli_console = console
    
    @abstractmethod
    def run(self, user_message: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Run the agent - must be implemented by subclasses."""
        pass
    
    @abstractmethod
    def _build_system_prompt(self) -> str:
        """Build system prompt with tool descriptions."""
        pass

    def __make_include_predicate(self, patterns: Optional[Iterable[str]]) -> Optional[Callable[[str], bool]]:
        if not patterns:
            return None
        pats = [p for p in patterns if isinstance(p, str) and p.strip()]
        if not pats:
            return None
    
        def _pred(name: str) -> bool:
            return any(fnmatch.fnmatch(name, p) for p in pats)
        return _pred

    async def _ensure_mcp_synced(self):
        if self._mcp_mgr is not None:
            return

        async with self._mcp_init_lock:
            if self._mcp_mgr is not None:
                return

            mcp_cfg = self.config.mcp or MCPConfig()
            if not mcp_cfg.enabled:
                self._mcp_mgr = MCPServerManager()
                return

            servers = mcp_cfg.servers or []
            if not servers:
                self._mcp_mgr = MCPServerManager()
                return

            mgr = MCPServerManager()

            global_isolated = bool(mcp_cfg.isolated)

            for s in servers:
                if not s.enabled:
                    continue
                name = s.name 
                command = s.command or "npx"
                args = list(s.args or [])

                server_isolated = s.isolated and global_isolated
                if server_isolated and not any(a == "--isolated" for a in args):
                    args.append("--isolated")

                try:
                    await mgr.add_stdio_server(name, command, args)
                except Exception as e:
                    self.cli_console.print(f"[MCP] Failed to start server: {e}", "yellow")

            for s in servers:
                if not s.enabled:
                    continue
                name = s.name
                include_pred = self.__make_include_predicate(s.include)
                save_dir = s.save_images_dir

                await sync_mcp_server_tools_into_registry(
                    server_name=name,
                    manager=mgr,
                    tool_registry=self.tool_registry,
                    include=include_pred,
                    save_images_dir=save_dir,
                )

            self._mcp_mgr = mgr

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

