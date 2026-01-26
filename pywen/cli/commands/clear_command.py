"""清屏命令实现"""
import os
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from .base_command import BaseCommand, CommandResult, CommandAction

class ClearCommand(BaseCommand):
    def __init__(self):
        super().__init__("clear", "clear the screen and conversation history")
    
    async def execute(self, context, args: str) ->  CommandResult:
        """清屏并重置对话历史"""
        console = context.get('console')
        
        # 检查是否有 --force 或 -f 参数跳过确认
        if args and ('-f' in args or '--force' in args):
            await self._perform_clear(context)
            return  CommandResult(action=CommandAction.HANDLED, text="Screen cleared and conversation history reset.") 
        
        # 询问用户确认
        if console:
            console.print("[yellow]This will clear the screen and reset conversation history.[/yellow]")
            try:
                
                session = PromptSession()
                response = await session.prompt_async(
                    HTML('<ansiblue>Are you sure you want to continue? (y/N): </ansiblue>')
                )
                
                if response.lower().strip() in ['y', 'yes']:
                    await self._perform_clear(context)
                else:
                    console.print("[dim]Clear operation cancelled.[/dim]")
                    console.print("")
            except KeyboardInterrupt:
                console.print("\n[dim]Clear operation cancelled.[/dim]")
                console.print("")
            except Exception as e:
                console.print(f"[dim]Clear operation cancelled: {e}[/dim]")
                console.print("")
        
        return  CommandResult(action=CommandAction.HANDLED) 
    
    async def _perform_clear(self, context):
        """执行清屏操作"""
        # 清屏
        os.system('cls' if os.name == 'nt' else 'clear')
        
        # 重置智能体对话历史
        agent_mgr = context.get('agent_mgr')
        if agent_mgr and hasattr(agent_mgr.current, 'reset_conversation'):
            agent_mgr.current.reset_conversation()
        
        console = context.get('console')
        if console:
            console.show_interactive_banner()
            console.show_status_bar()
            console.print("[green]Screen cleared and conversation history reset.[/green]")
            console.print("")
