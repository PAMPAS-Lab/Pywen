import asyncio
import atexit
import contextlib
import locale
import os
import re
import shlex
import signal
import tempfile
from typing import Any, Mapping, Optional, Set, Tuple

from pywen.tools.tool_manager import register_tool

from .base_tool import BaseTool, ToolCallResult, ToolRiskLevel

# 配置常量
MAX_OUTPUT_LENGTH = 30000
DEFAULT_TIMEOUT = 120  # 默认超时时间（秒）
INITIAL_WAIT_TIME = 5.0  # 初始等待时间（秒），用于检测命令是否快速完成
READ_BUFFER_SIZE = 4096  # 读取缓冲区大小（字节）
READ_TIMEOUT = 0.5  # 单次读取超时时间（秒）
BACKGROUND_STARTUP_DELAY = 1.0  # 后台进程启动延迟（秒）
BACKGROUND_READ_TIMEOUT = 1.0  # 后台进程初始输出读取超时（秒）

# 配置常量
MAX_OUTPUT_LENGTH = 30000
DEFAULT_TIMEOUT = 120  # 默认超时时间（秒）
INITIAL_WAIT_TIME = 5.0  # 初始等待时间（秒），用于检测命令是否快速完成
READ_BUFFER_SIZE = 4096  # 读取缓冲区大小（字节）
READ_TIMEOUT = 0.5  # 单次读取超时时间（秒）
BACKGROUND_STARTUP_DELAY = 1.0  # 后台进程启动延迟（秒）
BACKGROUND_READ_TIMEOUT = 1.0  # 后台进程初始输出读取超时（秒）

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

_tracked_pids: Set[int] = set()
_cleanup_registered = False


def _cleanup_all_processes():
    """在程序退出时清理所有跟踪的进程"""
    global _tracked_pids
    for pid in list(_tracked_pids):
        try:
            if os.name == "nt":
                os.kill(pid, signal.SIGTERM)
            else:
                # 尝试终止进程组
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    # 进程组不存在，尝试终止单个进程
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    _tracked_pids.clear()


def _register_cleanup():
    """注册退出清理钩子"""
    global _cleanup_registered
    if not _cleanup_registered:
        atexit.register(_cleanup_all_processes)
        if os.name != "nt":
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    old_handler = signal.getsignal(sig)
                    def handler(signum, frame, old=old_handler):
                        _cleanup_all_processes()
                        if callable(old) and old not in (signal.SIG_IGN, signal.SIG_DFL):
                            old(signum, frame)
                        elif old == signal.SIG_DFL:
                            signal.signal(signum, signal.SIG_DFL)
                            os.kill(os.getpid(), signum)
                    signal.signal(sig, handler)
                except (ValueError, OSError):
                    pass
        _cleanup_registered = True


def track_pid(pid: int):
    """添加 PID 到跟踪列表"""
    _register_cleanup()
    _tracked_pids.add(pid)


def untrack_pid(pid: int):
    """从跟踪列表移除 PID"""
    _tracked_pids.discard(pid)
@register_tool(name="bash", providers=["pywen", "claude",])
class BashTool(BaseTool):
    """Shell 命令执行工具"""

    if os.name == "nt":
        description = """Run commands in Windows Command Prompt (cmd.exe)"""
    else:
        description = """Run commands in a bash shell. Command is executed as `bash -c <command>`."""

    name = "bash"
    display_name = "Bash Command" if os.name != "nt" else "Windows Command"
    parameter_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute"
            },
            "is_background": {
                "type": "boolean",
                "description": "Whether to run the command in background. Set to true for long-running processes like servers.",
                "default": False
            },
            "directory": {
                "type": "string",
                "description": "The working directory to run the command in. If not provided, uses current directory."
            },
            "timeout": {
                "type": "number",
                "description": f"Command timeout in seconds. Default is {DEFAULT_TIMEOUT} seconds.",
                "default": DEFAULT_TIMEOUT
            }
        },
        "required": ["command"]
    }
    risk_level = ToolRiskLevel.LOW

    def __init__(self):
        super().__init__()
        self._encoding = 'utf-8'
        if os.name == "nt":
            try:
                self._encoding = locale.getpreferredencoding() or 'gbk'
                if self._encoding.lower() in ['cp936', 'gbk']:
                    self._encoding = 'gbk'
                elif self._encoding.lower() in ['utf-8', 'utf8']:
                    self._encoding = 'utf-8'
            except Exception:
                self._encoding = 'gbk'

        self._background_processes: dict[int, asyncio.subprocess.Process] = {}

    def get_risk_level(self, **kwargs) -> ToolRiskLevel:
        """根据命令评估风险等级"""
        command = kwargs.get("command", "")

        high_risk_commands = ["rm -rf", "del /s", "format", "fdisk", "mkfs", "dd", "shutdown", "reboot"]
        if any(cmd in command.lower() for cmd in high_risk_commands):
            return ToolRiskLevel.HIGH

        medium_risk_commands = ["rm", "del", "mv", "cp", "chmod", "chown", "sudo", "su"]
        if any(cmd in command.lower() for cmd in medium_risk_commands):
            return ToolRiskLevel.MEDIUM

        return ToolRiskLevel.LOW

    async def _generate_confirmation_message(self, **kwargs) -> str:
        """生成确认消息"""
        command = kwargs.get("command", "")
        risk_level = self.get_risk_level(**kwargs)

        message = "🔧 Execute bash command:\n"
        message += f"Command: {command}\n"
        message += f"Risk Level: {risk_level.value.upper()}\n"

        if risk_level == ToolRiskLevel.HIGH:
            message += "⚠️  WARNING: This is a HIGH RISK command that could cause system damage!\n"
        elif risk_level == ToolRiskLevel.MEDIUM:
            message += "⚠️  CAUTION: This command may modify files or system state.\n"

        return message

    def _truncate_output(self, output: str) -> str:
        """截断过长的输出"""
        if len(output) > MAX_OUTPUT_LENGTH:
            half = MAX_OUTPUT_LENGTH // 2
            return (
                output[:half] +
                f"\n\n... [truncated {len(output) - MAX_OUTPUT_LENGTH} characters] ...\n\n" +
                output[-half:]
            )
        return output

    def _prepare_command(self, command: str) -> Tuple[str, Optional[str]]:
        """
        准备命令执行方式，返回 (shell_command, temp_script_path)

        对于多行命令，使用临时脚本文件方式，更安全且可控。
        对于单行命令，使用 bash -c 方式。
        """
        if os.name == "nt":
            return (f'cmd.exe /c "({command})"', None)

        if '\n' in command:
            try:
                fd, temp_script = tempfile.mkstemp(suffix='.sh', prefix='pywen_bash_', text=True)
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as f:
                        f.write('#!/bin/bash\n')
                        f.write('set -e\n')
                        f.write(command)
                        f.write('\n')
                    os.chmod(temp_script, 0o755)
                    return (f'bash {shlex.quote(temp_script)}', temp_script)
                except Exception:
                    try:
                        os.close(fd)
                        os.unlink(temp_script)
                    except Exception:
                        pass
                    raise
            except Exception:
                single_line = '; '.join(line.strip() for line in command.split('\n') if line.strip())
                escaped_command = single_line.replace("'", "'\"'\"'")
                return (f"bash -c '({escaped_command})'", None)
        else:
            escaped_command = command.replace("'", "'\"'\"'")
            return (f"bash -c '({escaped_command})'", None)

    async def execute(self, **kwargs) -> ToolCallResult:
        """执行 bash 命令"""
        command = kwargs.get("command")
        is_background = kwargs.get("is_background", False)
        directory = kwargs.get("directory")
        timeout = kwargs.get("timeout", DEFAULT_TIMEOUT)

        if not command:
            return ToolCallResult(call_id="", error="No command provided")

        cwd = directory or os.getcwd()
        if directory and not os.path.isdir(directory):
            return ToolCallResult(call_id="", error=f"Directory does not exist: {directory}")

        # 自动为 grep 命令添加 --line-buffered 选项
        if os.name != "nt" and "grep" in command and "--line-buffered" not in command:
            command = re.sub(r'\bgrep\b', 'grep --line-buffered', command)

        # 准备命令执行方式
        shell_command, temp_script = self._prepare_command(command)

        try:
            if is_background:
                return await self._execute_background(shell_command, command, cwd)
            return await self._execute_foreground(shell_command, cwd, timeout)
        finally:
            if temp_script and os.path.exists(temp_script):
                with contextlib.suppress(Exception):
                    os.unlink(temp_script)

    async def _execute_foreground(
        self,
        shell_command: str,
        cwd: str,
        timeout: float
    ) -> ToolCallResult:
        """前台执行命令"""
        try:
            env = os.environ.copy()
            env.update({
                "PAGER": "cat",
                "MANPAGER": "cat",
                "GIT_PAGER": "cat",
                "LESS": "-R",
                "PIP_PROGRESS_BAR": "off",
                "TQDM_DISABLE": "1",
                "PYTHONUNBUFFERED": "1",
            })

            process = await asyncio.create_subprocess_shell(
                shell_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=(os.name != "nt"),
            )
            return await self._read_with_progress(process, timeout)

        except Exception as e:
            return ToolCallResult(call_id="", error=f"Error executing command: {str(e)}")

    async def _read_with_progress(
        self,
        process: asyncio.subprocess.Process,
        timeout: float
    ) -> ToolCallResult:
        """增量读取命令输出"""
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        start_time = asyncio.get_event_loop().time()
        initial_wait = min(INITIAL_WAIT_TIME, timeout)

        async def read_available(stream, chunks: list[str]):
            if stream is None:
                return
            while True:
                try:
                    data = await asyncio.wait_for(stream.read(READ_BUFFER_SIZE), timeout=READ_TIMEOUT)
                    if not data:
                        break
                    chunks.append(data.decode(self._encoding, errors='replace'))
                except asyncio.TimeoutError:
                    break

        try:
            done, pending = await asyncio.wait(
                [asyncio.create_task(process.wait())],
                timeout=initial_wait
            )
            if done:
                stdout, stderr = await process.communicate()
                stdout_text = stdout.decode(self._encoding, errors='replace') if stdout else ""
                stderr_text = stderr.decode(self._encoding, errors='replace') if stderr else ""
                return self._format_result(process.returncode or 0, stdout_text, stderr_text)
        except asyncio.TimeoutError:
            pass

        if process.stdout:
            await read_available(process.stdout, stdout_chunks)
        if process.stderr:
            await read_available(process.stderr, stderr_chunks)

        stdout_text = ''.join(stdout_chunks)
        stderr_text = ''.join(stderr_chunks)

        if stdout_text or stderr_text:
            track_pid(process.pid)
            result_parts = []
            if stdout_text:
                result_parts.append(stdout_text.strip())
            if stderr_text:
                result_parts.append(f"[stderr]: {stderr_text.strip()}")
            result_parts.append(f"\n⏳ Process still running (PID: {process.pid})")
            result_parts.append(f"💡 Use `kill {process.pid}` to stop it")
            return ToolCallResult(
                call_id="",
                result='\n'.join(result_parts),
                metadata={"pid": process.pid, "still_running": True}
            )

        elapsed = asyncio.get_event_loop().time() - start_time
        remaining_timeout = timeout - elapsed

        if remaining_timeout > 0:
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=remaining_timeout
                )
                stdout_text = stdout.decode(self._encoding, errors='replace') if stdout else ""
                stderr_text = stderr.decode(self._encoding, errors='replace') if stderr else ""
                return self._format_result(process.returncode or 0, stdout_text, stderr_text)
            except asyncio.TimeoutError:
                pass

        if process.returncode is None:
            track_pid(process.pid)
            return ToolCallResult(
                call_id="",
                result=f"⏳ Command running in background (PID: {process.pid})\n"
                       f"💡 No output yet after {timeout}s. Use `kill {process.pid}` to stop.",
                metadata={"pid": process.pid, "still_running": True}
            )

        process.kill()
        await process.wait()
        return ToolCallResult(
            call_id="",
            error=f"Command timed out after {timeout} seconds"
        )

    async def _execute_background(self, shell_command: str, original_command: str, cwd: str) -> ToolCallResult:
        """后台执行命令"""
        try:
            env = os.environ.copy()
            env.update({
                "PAGER": "cat",
                "MANPAGER": "cat",
                "GIT_PAGER": "cat",
                "LESS": "-R",
                "PIP_PROGRESS_BAR": "off",
                "TQDM_DISABLE": "1",
                "PYTHONUNBUFFERED": "1",
            })

            process = await asyncio.create_subprocess_shell(
                shell_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=(os.name != "nt"),
            )
            pid = process.pid

            await asyncio.sleep(BACKGROUND_STARTUP_DELAY)

            initial_output = ""
            if process.stdout:
                try:
                    stdout_data = await asyncio.wait_for(
                        process.stdout.read(READ_BUFFER_SIZE),
                        timeout=BACKGROUND_READ_TIMEOUT
                    )
                    initial_output = stdout_data.decode(self._encoding, errors='replace')
                except asyncio.TimeoutError:
                    pass

            if process.returncode is not None and process.returncode != 0:
                stderr_data = await process.stderr.read() if process.stderr else b""
                stderr_text = stderr_data.decode(self._encoding, errors='replace')
                return ToolCallResult(call_id="", error=f"Background process failed to start:\n{stderr_text}")

            self._background_processes[pid] = process
            track_pid(pid)

            result_lines = [
                f"Command: {original_command}",
                f"Directory: {cwd}",
                f"Output: {initial_output.strip() if initial_output else '(starting...)'}",
                f"PID: {pid}",
            ]

            result_text = '\n'.join(result_lines)
            result_text += "\n\n✅ Background process started"
            if os.name != "nt":
                result_text += f"\n📝 To stop: kill {pid}"

            return ToolCallResult(
                call_id="",
                result=result_text,
                metadata={"pid": pid, "is_background": True}
            )
        except Exception as e:
            return ToolCallResult(call_id="", error=f"Error starting background process: {str(e)}")

    def _format_result(self, exit_code: int, stdout: str, stderr: str) -> ToolCallResult:
        """格式化命令执行结果"""
        stdout = self._truncate_output(stdout.strip())
        stderr = self._truncate_output(stderr.strip())

        result_parts = []
        if stdout:
            result_parts.append(stdout)
        if stderr:
            result_parts.append(f"[stderr]: {stderr}")
        if exit_code != 0:
            result_parts.append(f"[Exit Code: {exit_code}]")
        if not result_parts:
            result_parts.append("Command executed successfully (no output)")

        result_text = '\n'.join(result_parts)

        if exit_code != 0:
            return ToolCallResult(call_id="", result=result_text, metadata={"exit_code": exit_code})

        return ToolCallResult(call_id="", result=result_text)

    async def kill_background(self, pid: int) -> ToolCallResult:
        """终止后台进程"""
        try:
            if os.name == "nt":
                os.kill(pid, signal.SIGTERM)
            else:
                os.killpg(pid, signal.SIGTERM)
            untrack_pid(pid)
            if pid in self._background_processes:
                del self._background_processes[pid]
            return ToolCallResult(call_id="", result=f"Process {pid} terminated")
        except Exception as e:
            return ToolCallResult(call_id="", error=f"Failed to kill process: {e}")

    def build(self, provider: str = "", func_type: str = "") -> Mapping[str, Any]:
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
