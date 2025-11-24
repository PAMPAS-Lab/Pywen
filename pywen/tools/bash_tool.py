import asyncio
import os
import locale
import re
from typing import Any, Mapping
from .base_tool import BaseTool, ToolResult, ToolRiskLevel
from pywen.core.tool_registry2 import register_tool

CLAUDE_DESCRIPTION = """
Executes a given bash command in a persistent shell session with optional timeout, 
ensuring proper handling and security measures.

Before executing the command, please follow these steps:

1. Directory Verification:
   - If the command will create new directories or files, first use the LS tool to verify the parent directory exists and is the correct location
   - For example, before running "mkdir foo/bar", first use LS to check that "foo" exists and is the intended parent directory

2. Command Execution:
   - Always quote file paths that contain spaces with double quotes (e.g., cd "path with spaces/file.txt")
   - Examples of proper quoting:
     - cd "/Users/name/My Documents" (correct)
     - cd /Users/name/My Documents (incorrect - will fail)
     - python "/path/with spaces/script.py" (correct)
     - python /path/with spaces/script.py (incorrect - will fail)
   - After ensuring proper quoting, execute the command.
   - Capture the output of the command.

Usage notes:
  - The command argument is required.
  - You can specify an optional timeout in milliseconds (up to 600000ms / 10 minutes). If not specified, commands will timeout after 120000ms (2 minutes).
  - It is very helpful if you write a clear, concise description of what this command does in 5-10 words.
  - If the output exceeds 30000 characters, output will be truncated before being returned to you.
  - You can use the `run_in_background` parameter to run the command in the background, which allows you to continue working while the command runs. You can monitor the output using the Bash tool as it becomes available. Never use `run_in_background` to run 'sleep' as it will return immediately. You do not need to use '&' at the end of the command when using this parameter.
  - VERY IMPORTANT: You MUST avoid using search commands like `find` and `grep`. Instead use Grep, Glob, or Task to search. You MUST avoid read tools like `cat`, `head`, `tail`, and `ls`, and use Read and LS to read files.
 - If you _still_ need to run `grep`, STOP. ALWAYS USE ripgrep at `rg` first, which all Claude Code users have pre-installed.
  - When issuing multiple commands, use the ';' or '&&' operator to separate them. DO NOT use newlines (newlines are ok in quoted strings).
  - Try to maintain your current working directory throughout the session by using absolute paths and avoiding usage of `cd`. You may use `cd` if the User explicitly requests it.
"""
@register_tool(name="bash", providers=["qwen", "claude",])
class BashTool(BaseTool):
    if os.name == "nt":
        description = """Run commands in Windows Command Prompt (cmd.exe)"""
    else:
        description = """Run commands in a bash shell"""
    name="bash"
    display_name="Bash Command" if os.name != "nt" else "Windows Command"
    description=description
    parameter_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute"
            }
        },
        "required": ["command"]
    }
    risk_level=ToolRiskLevel.LOW 
    _encoding = 'utf-8'
    if os.name == "nt":
        try:
            # Windows 系统编码检测
            self._encoding = locale.getpreferredencoding() or 'gbk'
            if self._encoding.lower() in ['cp936', 'gbk']:
                self._encoding = 'gbk'
            elif self._encoding.lower() in ['utf-8', 'utf8']:
                self._encoding = 'utf-8'
        except:
            self._encoding = 'gbk'
    
    def get_risk_level(self, **kwargs) -> ToolRiskLevel:
        """Get risk level based on the command."""
        command = kwargs.get("command", "")

        # High risk commands
        high_risk_commands = ["rm -rf", "del /s", "format", "fdisk", "mkfs", "dd", "shutdown", "reboot"]
        if any(cmd in command.lower() for cmd in high_risk_commands):
            return ToolRiskLevel.HIGH

        # Medium risk commands
        medium_risk_commands = ["rm", "del", "mv", "cp", "chmod", "chown", "sudo", "su"]
        if any(cmd in command.lower() for cmd in medium_risk_commands):
            return ToolRiskLevel.MEDIUM

        # Default to low risk
        return ToolRiskLevel.LOW

    async def _generate_confirmation_message(self, **kwargs) -> str:
        """Generate detailed confirmation message for bash commands."""
        command = kwargs.get("command", "")
        risk_level = self.get_risk_level(**kwargs)

        message = f"🔧 Execute bash command:\n"
        message += f"Command: {command}\n"
        message += f"Risk Level: {risk_level.value.upper()}\n"

        if risk_level == ToolRiskLevel.HIGH:
            message += "⚠️  WARNING: This is a HIGH RISK command that could cause system damage!\n"
        elif risk_level == ToolRiskLevel.MEDIUM:
            message += "⚠️  CAUTION: This command may modify files or system state.\n"

        return message
    
    async def execute(self, **kwargs) -> ToolResult:
        """Execute bash command with streaming output."""
        command = kwargs.get("command")

        if not command:
            return ToolResult(call_id="", error="No command provided")

        # 在输出开头显示执行的命令
        command_header = f"$ {command}\n"
        
        # 检测是否是长时间运行的命令
        long_running_patterns = [
            r'python.*\.py',
            r'flask.*run',
            r'uvicorn',
            r'streamlit.*run',
            r'gradio',
            r'npm.*start',
            r'node.*server',
            r'python.*-m.*http\.server',
            r'http\.server'
        ]
        
        is_long_running = any(re.search(pattern, command, re.IGNORECASE) for pattern in long_running_patterns)
        
        try:
            if os.name == "nt":
                process = await asyncio.create_subprocess_shell(
                    f'cmd.exe /c "{command}"',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,  # 合并stderr到stdout
                    stdin=asyncio.subprocess.DEVNULL
                )
            else:
                # Use bash -c to ensure full shell feature support (brace expansion, etc.)
                escaped_command = command.replace("'", "'\"'\"'")
                process = await asyncio.create_subprocess_shell(
                    f"bash -c '{escaped_command}'",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.DEVNULL
                )
            
            if is_long_running:
                # 流式读取输出
                output_chunks = [command_header]  # 开头显示命令
                start_time = asyncio.get_event_loop().time()
                
                while True:
                    try:
                        # 读取一行或等待0.5秒
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=0.5)
                        if not line:
                            break
                        
                        try:
                            line_text = line.decode('utf-8').strip()
                        except UnicodeDecodeError:
                            line_text = line.decode(self._encoding, errors='replace').strip()
                        
                        if line_text:
                            output_chunks.append(line_text)
                            
                            # 检查是否有服务器启动信息
                            if any(keyword in line_text.lower() for keyword in ['running on', 'serving at', 'listening on', 'server started', 'serving http']):
                                port_match = re.search(r'(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d+)', line_text)
                                if port_match:
                                    port = port_match.group(1)
                                    server_info = f"\n🌐 Server started! Access at: http://localhost:{port}"
                                    server_info += f"\n📝 To stop the server, use Ctrl+C or close this process"
                                    output_chunks.append(server_info)
                                    
                                    # 服务器启动后立即返回结果
                                    result_text = "\n".join(output_chunks)
                                    result_text += "\n\n✅ Server is running in background"
                                    return ToolResult(
                                        call_id="",
                                        result=result_text,
                                        metadata={"process_running": True, "server_port": port}
                                    )
                            
                            # 每收集3行或运行超过2秒就返回一次结果
                            if len(output_chunks) >= 3 or (asyncio.get_event_loop().time() - start_time) > 2:
                                result_text = "\n".join(output_chunks)
                                if process.returncode is None:  # 进程还在运行
                                    result_text += "\n\n⏳ Process is still running..."
                                
                                return ToolResult(
                                    call_id="",
                                    result=result_text,
                                    metadata={"process_running": process.returncode is None}
                                )
                    
                    except asyncio.TimeoutError:
                        # 检查进程是否还在运行
                        if process.returncode is not None:
                            break
                        
                        # 如果有输出就返回
                        if output_chunks:
                            result_text = "\n".join(output_chunks)
                            result_text += "\n\n⏳ Process is still running..."
                            return ToolResult(
                                call_id="",
                                result=result_text,
                                metadata={"process_running": True}
                            )
                        
                        # 运行时间超过30秒且没有输出，提示用户
                        if (asyncio.get_event_loop().time() - start_time) > 10:
                            return ToolResult(
                                call_id="",
                                result="Process is running but no output detected after 30 seconds.\n"
                                       "This might be a server or long-running process.\n"
                                       "Check common ports: http://localhost:5000, http://localhost:8000",
                                metadata={"process_running": True}
                            )
            
                # 进程结束，返回最终结果
                if output_chunks:
                    return ToolResult(call_id="", result="\n".join(output_chunks))
                else:
                    return ToolResult(call_id="", result=f"{command_header}Process completed with no output")
            
            else:
                # 普通命令，正常等待完成
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    return ToolResult(call_id="", error="Command timed out after 120 seconds")
                
                # 解码输出
                try:
                    stdout_text = stdout.decode('utf-8') if stdout else ""
                except UnicodeDecodeError:
                    stdout_text = stdout.decode(self._encoding, errors='replace') if stdout else ""
                
                # 根据退出码和命令类型判断如何处理结果
                if process.returncode == 0:
                    # 成功执行
                    result_text = command_header + (stdout_text or "Command executed successfully")
                    return ToolResult(call_id="", result=result_text)
                elif process.returncode == 1:
                    # 退出码1通常表示"未成功"但不一定是错误
                    # 对于某些命令（grep、diff等），这是正常的预期行为
                    result_text = command_header + (stdout_text or "⚠️ Command exited with code 1")
                    return ToolResult(call_id="", result=result_text)
                else:
                    # 退出码 >= 2 通常表示真正的错误（语法错误、文件不存在等）
                    error_text = command_header + f"Command failed with exit code {process.returncode}"
                    if stdout_text:
                        error_text += f"\nOutput:\n{stdout_text}"
                    return ToolResult(call_id="", error=error_text)
        
        except Exception as e:
            return ToolResult(call_id="", error=f"Error executing command: {str(e)}")

    def build(self, provider:str = "", func_type: str = "") -> Mapping[str, Any]:
        if provider.lower() == "claude" or provider.lower() == "anthropic":
            res = {
                "name": self.name,
                "description": CLAUDE_DESCRIPTION,
                "input_schema": self.parameter_schema,
            }
        else:
            res = {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameter_schema
                }
            }
        return res
