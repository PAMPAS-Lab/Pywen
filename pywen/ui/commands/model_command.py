"""Model切换命令实现"""

from rich import get_console
from .base_command import BaseCommand
from pywen.config.manager import ConfigManager
from typing import Dict, Any

class ModelCommand(BaseCommand):
    def __init__(self):
        super().__init__("model", "switch between different model providers")
        self.console = get_console()
    
    async def execute(self, context: Dict[str, Any], args: str) -> bool:
        """处理model切换命令"""
        parts = args.strip().split() if args.strip() else []
        
        if len(parts) == 0:
            # 显示可用model列表
            self._show_available_models(context)
        elif len(parts) == 1:
            # 切换model
            await self._switch_model(context, parts[0])
        else:
            self.console.print("[red]Usage: /model [provider_name][/red]")
            self.console.print("")
        
        return True
    
    def _show_available_models(self, context: Dict[str, Any]):
        """显示可用model列表"""
        config = context.get('config')
        if not config:
            self.console.print("[red]No config available[/red]")
            return
        
        # 读取配置文件获取所有model_providers
        config_mgr = ConfigManager()
        try:
            # 直接读取配置文件以获取所有 providers
            config_data = ConfigManager._read_json(config_mgr.config_path)
            model_providers = config_data.get("model_providers", {})
            default_provider = config_data.get("default_provider", "qwen")
        except Exception as e:
            self.console.print(f"[red]Failed to read config: {e}[/red]")
            return
        
        if not model_providers:
            self.console.print("[yellow]No model providers configured[/yellow]")
            return
        
        self.console.print("[bold]Available Model Providers:[/bold]")
        for provider_name, provider_config in model_providers.items():
            model_name = provider_config.get("model", "N/A")
            status = "[green]✓ Current[/green]" if provider_name == default_provider else ""
            self.console.print(f"  • [cyan]{provider_name}[/cyan]: {model_name} {status}")
        self.console.print(f"\n[dim]Usage: /model <provider_name> to switch[/dim]")
    
    async def _switch_model(self, context: Dict[str, Any], new_provider: str):
        """切换model provider"""
        config = context.get('config')
        if not config:
            self.console.print("[red]No config available[/red]")
            return
        
        config_mgr = ConfigManager()
        try:
            # 直接读取配置文件以获取所有 providers
            config_data = ConfigManager._read_json(config_mgr.config_path)
            model_providers = config_data.get("model_providers", {})
            current_provider = config_data.get("default_provider", "qwen")
        except Exception as e:
            self.console.print(f"[red]Failed to read config: {e}[/red]")
            return
        
        # 检查provider是否存在
        if new_provider not in model_providers:
            self.console.print(f"[red]Unknown model provider: {new_provider}[/red]")
            self.console.print(f"[dim]Available providers: {', '.join(model_providers.keys())}[/dim]")
            return
        
        # 检查是否已经是当前provider
        if new_provider == current_provider:
            model_name = model_providers[new_provider].get("model", "N/A")
            self.console.print(f"[yellow]Already using provider '{new_provider}' with model '{model_name}'[/yellow]")
            return
        
        try:
            # 更新default_provider并保存
            config_data["default_provider"] = new_provider
            config_mgr.write_config_data(config_data)
            
            # 重新加载配置
            new_config = config_mgr.load(interactive_bootstrap=False)
            
            # 获取当前agent类型
            current_agent = context.get('agent')
            agent_type = self._get_current_agent_type(current_agent)
            
            # 重新创建agent
            hook_mgr = context.get('hook_mgr')
            new_agent = self._create_agent(new_config, hook_mgr, agent_type)
            new_agent.set_cli_console(context.get('console'))
            
            # 更新context中的agent和config
            context['agent'] = new_agent
            context['config'] = new_config
            
            model_name = model_providers[new_provider].get("model", "N/A")
            self.console.print(f"[green]Switched to model provider '{new_provider}' with model '{model_name}'[/green]")
            
        except Exception as e:
            self.console.print(f"[red]Failed to switch model: {e}[/red]")
    
    def _get_current_agent_type(self, agent) -> str:
        """获取当前agent类型"""
        if agent is None:
            return "qwen"  # 默认使用qwen agent
        
        # 动态导入避免循环依赖
        try:
            from pywen.agents.qwen.qwen_agent import QwenAgent
            from pywen.agents.research.google_research_agent import GeminiResearchDemo
            from pywen.agents.claudecode.claude_code_agent import ClaudeCodeAgent

            if isinstance(agent, QwenAgent):
                return "qwen"
            elif isinstance(agent, GeminiResearchDemo):
                return "research"
            elif isinstance(agent, ClaudeCodeAgent):
                return "claude"
        except ImportError:
            pass

        return "qwen"  # 默认使用qwen agent
    
    def _create_agent(self, config, hook_mgr, agent_type: str):
        """创建agent实例"""
        if agent_type == "qwen":
            from pywen.agents.qwen.qwen_agent import QwenAgent
            return QwenAgent(config, hook_mgr)
        elif agent_type == "research":
            from pywen.agents.research.google_research_agent import GeminiResearchDemo
            return GeminiResearchDemo(config)
        elif agent_type == "claude":
            from pywen.agents.claudecode.claude_code_agent import ClaudeCodeAgent
            return ClaudeCodeAgent(config, hook_mgr)
        else:
            # 默认使用qwen
            from pywen.agents.qwen.qwen_agent import QwenAgent
            return QwenAgent(config, hook_mgr)
