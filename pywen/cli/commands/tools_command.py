"""Tools command implementation"""
from typing import Dict, Any
from rich import get_console
from rich.table import Table
from .base_command import BaseCommand, CommandResult, CommandAction
from pywen.tools.tool_manager import ToolManager

class ToolsCommand(BaseCommand):
    def __init__(self):
        super().__init__("tools", "list available Pywen tools")
        self.console = get_console()
    
    async def execute(self, context: Dict[str, Any], args: str) -> CommandResult:
        """显示可用工具列表"""
        agent_mgr  = context.get('agent_mgr')
        
        if not agent_mgr:
            self.console.print("[red]No agent manager available[/red]")
            return CommandResult(action=CommandAction.HANDLED, error="no agent manager available")
        
        try:
            provider = agent_mgr.current_name.lower().replace("agent", "")
            tools = ToolManager.list_for_provider(provider)
             
            table = Table(title=f"{agent_mgr.current_name} Available Tools")
            table.add_column("Tool Name", style="green")
            table.add_column("Display Name", style="green")
            table.add_column("Description", style="white")
            
            # 添加工具信息
            for tool in tools:
                tool_name = tool.name
                display_name = tool.display_name
                description = tool.description
                table.add_row(tool_name, display_name, description)
            
            self.console.print(table)
            self.console.print(f"\n[dim]Total: {len(tools)} tools available[/dim]")
            
        except Exception as e:
            self.console.print(f"[red]Error accessing tool registry: {e}[/red]")
            import traceback
            self.console.print(f"[dim]{traceback.format_exc()}[/dim]")
        
        return CommandResult(action=CommandAction.HANDLED)

