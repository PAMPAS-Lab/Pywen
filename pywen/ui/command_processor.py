"""command processor"""

import subprocess
import os
from typing import Dict
from.commands.base_command import BaseCommand
from .commands.help_command import HelpCommand
from .commands.about_command import AboutCommand
from .commands.clear_command import ClearCommand
from .commands.quit_command import QuitCommand
from .commands.memory_command import MemoryCommand
from .commands.stats_command import StatsCommand
from .commands.agent_command import AgentCommand
from .commands.bug_command import BugCommand
from .commands.tools_command import ToolsCommand
from .commands.model_command import ModelCommand
from .commands.placeholder_commands import (
    PrivacyCommand, ThemeCommand, DocsCommand,
    EditorCommand, McpCommand, ExtensionsCommand,
    ChatCommand, CompressCommand
)

class CommandProcessor:
    def __init__(self):
        self.commands: Dict[str, BaseCommand] = {}
        self._register_commands()
    
    def _register_commands(self):
        """注册所有命令"""
        # 已实现的命令
        commands = [
            HelpCommand(),
            AboutCommand(),
            ClearCommand(),
            QuitCommand(),
            MemoryCommand(),
            StatsCommand(),
            AgentCommand(),
            BugCommand(),
            ToolsCommand(),
            ModelCommand(),
            # 占位符命令
            PrivacyCommand(),
            ThemeCommand(),
            DocsCommand(),
            EditorCommand(),
            McpCommand(),
            ExtensionsCommand(),
            ChatCommand(),
            CompressCommand(),
        ]
        
        for cmd in commands:
            self.commands[cmd.name] = cmd
            if cmd.alt_name:
                self.commands[cmd.alt_name] = cmd
    
    async def process_command(self, user_input: str, context: Dict) -> bool:
        """处理命令输入"""
        # 检查是否是感叹号命令（shell命令）
        if user_input.startswith('!'):
            return await self._handle_shell_command(user_input, context)
        
        # 检查是否是斜杠命令
        if not user_input.startswith('/'):
            return False
        
        # 解析命令
        parts = user_input[1:].split(' ', 1)
        command_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        # 查找并执行命令
        if command_name in self.commands:
            command = self.commands[command_name]
            await command.execute(context, args)
            return True
        
        # 未知命令
        console = context.get('console')
        if console:
            console.print(f"Unknown command: /{command_name}", "red")
            console.print("Type '/help' to see available commands.","dim")
        
        return True  # 返回True表示已处理（即使是错误）
    
    async def _handle_shell_command(self, user_input: str, context: Dict) -> bool:
        """处理感叹号开头的shell命令"""
        console = context.get('console')
        
        # 提取命令（去掉感叹号）
        shell_command = user_input[1:].strip()
        
        if not shell_command:
            if console:
                console.print("No command specified after '!'","red")
            return True
        
        # 特殊处理 cd 命令
        if shell_command.startswith('cd ') or shell_command == 'cd':
            return await self._handle_cd_command(shell_command, console)
        
        if console:
            console.print(f"Executing shell command:{shell_command}","cyan")
        
        try:
            # 执行shell命令
            result = subprocess.run(
                shell_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,  # 30秒超时
                cwd=os.getcwd()  # 使用当前工作目录
            )
            
            # 显示结果
            if result.stdout:
                if console:
                    console.print(f"Output:\n{result.stdout}", "orange3")
                    console.print("")  # 添加换行
            
            if result.stderr:
                if console:
                    console.print(f"Error output:\n{result.stderr}", "orange3")
                    console.print("")  # 添加换行
            
            if result.returncode != 0:
                if console:
                    console.print(f"Command exited with code: {result.returncode}", "orange3")
                    console.print("")  # 添加换行
            else:
                if console and not result.stdout and not result.stderr:
                    console.print("Command completed successfully (no output)", "orange3")
                    console.print("")  # 添加换行
                    
        except subprocess.TimeoutExpired:
            if console:
                console.print("Command timed out after 30 seconds", "red")
                console.print("")  # 添加换行
        except Exception as e:
            if console:
                console.print(f"Error executing command: {e}", "red")
                console.print("")  # 添加换行
        
        return True

    async def _handle_cd_command(self, command: str, console) -> bool:
        """特殊处理 cd 命令"""
        import os
        from pathlib import Path
        
        # 解析 cd 命令
        parts = command.split(' ', 1)
        if len(parts) == 1:
            # 只有 cd，切换到用户主目录
            target_dir = os.path.expanduser('~')
        else:
            # cd 后面有路径
            target_dir = parts[1].strip()
            
            # 处理特殊路径
            if target_dir == '~':
                target_dir = os.path.expanduser('~')
            elif target_dir == '-':
                # cd - 功能需要记录上一个目录，这里简化处理
                if console:
                    console.print("cd - not supported, use absolute path","yellow")
                return True
            else:
                # 展开用户目录符号和相对路径
                target_dir = os.path.expanduser(target_dir)
                if not os.path.isabs(target_dir):
                    target_dir = os.path.join(os.getcwd(), target_dir)
        
        try:
            # 规范化路径
            target_dir = os.path.abspath(target_dir)
            
            # 检查目录是否存在
            if not os.path.exists(target_dir):
                if console:
                    console.print(f"Directory does not exist: {target_dir}","red")
                return True
            
            if not os.path.isdir(target_dir):
                if console:
                    console.print(f"Not a directory: {target_dir}","red")
                return True
            
            # 改变当前工作目录
            old_dir = os.getcwd()
            os.chdir(target_dir)
            
            if console:
                console.print(f"Changed directory from {old_dir} to {os.getcwd()}", "orange3")
                console.print("")  # 添加换行
            
        except PermissionError:
            if console:
                console.print(f"Permission denied: {target_dir}", "red")
                console.print("")  # 添加换行
        except Exception as e:
            if console:
                console.print(f"Error changing directory: {e}", "red")
                console.print("")  # 添加换行
        
        return True
