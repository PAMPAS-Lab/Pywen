"""Bash command execution tool."""

import asyncio
import os
import locale
import re

from .base import BaseTool, ToolResult, ToolRiskLevel


class BashTool(BaseTool):
    """Tool for executing bash commands."""
    
    def __init__(self):
        # Set description based on OS
        if os.name == "nt":
            description = """Run commands in Windows Command Prompt (cmd.exe)"""
# """* Current platform: Windows - use Windows commands (dir, type, copy, etc.)
# * Common commands: dir (list files), type (view file), cd (change directory)
# * File paths should use backslashes or be quoted: "C:\\path\\to\\file"
# * State is persistent across command calls
# * Avoid commands that produce very large output
# * Please run long lived commands in the background, e.g. 'sleep 10 &'
# * Please use "python" and "pip" instead of "python3" and "pip3"
# """
        else:
            description = """Run commands in a bash shell"""
# * Current platform: Unix/Linux - use standard bash commands
# * You have access to common linux and python packages via apt and pip
# * State is persistent across command calls and discussions with the user
# * To inspect a particular line range of a file, e.g. lines 10-25, try 'sed -n 10,25p /path/to/the/file'
# * Please avoid commands that may produce a very large amount of output
# * Please run long lived commands in the background, e.g. 'sleep 10 &'
# * Please use "python" and "pip" instead of "python3" and "pip3"
# """
        
        super().__init__(
            name="bash",
            display_name="Bash Command" if os.name != "nt" else "Windows Command",
            description=description,
            parameter_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute"
                    }
                },
                "required": ["command"]
            },
            risk_level=ToolRiskLevel.LOW  # Default to low risk, will be elevated for dangerous commands
        )
        
        # 检测系统编码
        self._encoding = 'utf-8'
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
    
    async def execute(self, **kwargs) -> ToolResult:
        """Execute bash command with streaming output."""
        command = kwargs.get("command")
        
        if not command:
            return ToolResult(call_id="", error="No command provided")
        
        # 检测是否是长时间运行的命令
        long_running_patterns = [
            r'python.*\.py',
            r'flask.*run',
            r'uvicorn',
            r'streamlit.*run',
            r'gradio',
            r'npm.*start',
            r'node.*server'
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
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.DEVNULL
                )
            
            if is_long_running:
                # 流式读取输出
                output_chunks = []
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
                            if any(keyword in line_text.lower() for keyword in ['running on', 'serving at', 'listening on', 'server started']):
                                port_match = re.search(r'(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d+)', line_text)
                                if port_match:
                                    port = port_match.group(1)
                                    server_info = f"\n🌐 Server detected! Access at: http://localhost:{port}"
                                    server_info += f"\nCheck logs: tail -f server.log"
                                    output_chunks.append(server_info)
                            
                            # 每收集5行或运行超过3秒就返回一次结果
                            if len(output_chunks) >= 5 or (asyncio.get_event_loop().time() - start_time) > 3:
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
                    return ToolResult(call_id="", result="Process completed with no output")
            
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
                
                if process.returncode == 0:
                    return ToolResult(call_id="", result=stdout_text or "Command executed successfully")
                else:
                    return ToolResult(call_id="", error=f"Command failed with exit code {process.returncode}")
        
        except Exception as e:
            return ToolResult(call_id="", error=f"Error executing command: {str(e)}")




