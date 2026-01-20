"""Agent切换命令实现"""
from typing import Dict, Any
from pywen.cli.cli_console import CLIConsole 
from pywen.agents.agent_manager import AgentManager
from pywen.config.manager import ConfigManager
from .base_command import BaseCommand, CommandResult, CommandAction

class AgentCommand(BaseCommand):
    def __init__(self):
        super().__init__("agent", "switch between different agents")
    
    async def execute(self, context: Dict[str, Any], args: str) -> CommandResult:
        """处理agent切换命令"""
        parts = args.strip().split() if args.strip() else []
        agent_manager : AgentManager = context['agent_mgr']
        cli : CLIConsole = context['console']
        config_mgr : ConfigManager = context['config_mgr']
        agents  = agent_manager.list_agents()
        if len(parts) == 0:
            # 显示可用agent列表
            for agent in agents:
                if agent == agent_manager.current_name:
                    cli.print(f"* {agent} (current)")
                else:
                    cli.print(f"  {agent}")
        elif len(parts) == 1:
            # 切换agent
            if parts[0] not in agents:
                cli.print(f"agent '{parts[0]}' not found.")
                return  CommandResult(action=CommandAction.HANDLED, error=f"agent '{parts[0]}' not found.") 
            config_mgr.switch_active_agent(parts[0], None)
            await agent_manager.switch_to(parts[0])
            cli.print(f"switched to agent '{parts[0]}'.")
        
        return  CommandResult(action=CommandAction.HANDLED) 
