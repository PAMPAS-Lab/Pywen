
"""Codex-compatible Shell tool for Pywen.
"""
import asyncio
import os
import shlex
import sys
from typing import Any, Dict, Optional

from .base import BaseTool, ToolResult, ToolRiskLevel


class CodexShellTool(BaseTool):
    def __init__(self):
        if os.name == "nt":
            desc = "Run commands in Windows Command Prompt (cmd.exe) with optional cwd/env/timeout."
            display = "Codex Shell (Windows)"
        else:
            desc = "Run commands in a bash shell with optional cwd/env/timeout."
            display = "Codex Shell"

        super().__init__(
            name="shell",
            display_name=display,
            description=desc,
            parameter_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute."},
                    "cwd": {"type": "string", "description": "Working directory (optional)."},
                    "env": {"type": "object", "additionalProperties": {"type": "string"},
                            "description": "Environment overlay for this call."},
                    "timeout": {"type": "integer", "minimum": 1, "maximum": 3600,
                                "description": "Timeout in seconds (default 120)."},
                    "stream": {"type": "boolean",
                               "description": "Return early with partial output if process is still running."},
                    "background": {"type": "boolean",
                                   "description": "Start and return immediately (no streaming)."},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.LOW,
        )

    def get_risk_level(self, **kwargs) -> ToolRiskLevel:
        cmd = (kwargs.get("command") or "").lower()
        high = ["rm -rf", "format", "fdisk", "mkfs", "dd", "shutdown", "reboot"]
        if any(token in cmd for token in high):
            return ToolRiskLevel.HIGH
        medium = ["rm ", " mv ", " cp ", " chmod", " chown", " sudo", " su ", ":> ", "truncate"]
        if any(token in f" {cmd} " for token in medium):
            return ToolRiskLevel.MEDIUM
        return ToolRiskLevel.LOW

    async def _generate_confirmation_message(self, **kwargs) -> str:
        bits = []
        for k in ["command", "cwd", "timeout", "background"]:
            if k in kwargs and kwargs[k] not in (None, ""):
                bits.append(f"{k}={kwargs[k]}")
        rl = self.get_risk_level(**kwargs).value.upper()
        return "Execute Codex Shell:\n" + "\n".join(bits) + f"\nRisk Level: {rl}"

    async def execute(self, **kwargs) -> ToolResult:
        command: str = kwargs.get("command", "")
        if not command:
            return ToolResult(call_id="", error="No command provided")

        cwd: Optional[str] = kwargs.get("cwd") or None
        env_overlay: Dict[str, str] = kwargs.get("env") or {}
        timeout: int = int(kwargs.get("timeout") or 120)
        stream: bool = bool(kwargs.get("stream") or False)
        background: bool = bool(kwargs.get("background") or False)

        env = os.environ.copy()
        for k, v in env_overlay.items():
            if isinstance(v, (str, int, float)):
                env[str(k)] = str(v)
            else:
                env[str(k)] = str(v)

        if os.name == "nt":
            shell_cmd = f'cmd.exe /c "{command}"'
        else:
            # Use 'bash -lc' so that login shell init files may be honored and path expansions work
            shell_cmd = f"bash -lc {shlex.quote(command)}"

        header = f"$ {command}\n"

        try:
            proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=cwd or None,
                env=env,
            )

            if background:
                return ToolResult(
                    call_id="",
                    result=header + f"Started in background (pid={proc.pid}).",
                    metadata={"pid": proc.pid, "background": True},
                )

            if stream:
                chunks = [header]
                start = asyncio.get_event_loop().time()
                lines_seen = 0
                while True:
                    try:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.2)
                    except asyncio.TimeoutError:
                        line = b""
                    if not line:
                        if proc.returncode is not None:
                            break
                        if (asyncio.get_event_loop().time() - start) > 2.0 or lines_seen >= 50:
                            text = "".join(chunks)
                            if text.strip() == "$":
                                text = header  # ensure header at least
                            return ToolResult(
                                call_id="",
                                result=text + "\n⏳ Process is still running...",
                                metadata={"process_running": True, "pid": proc.pid},
                            )
                        continue
                    try:
                        decoded = line.decode("utf-8", errors="replace")
                    except Exception:
                        decoded = line.decode(sys.getdefaultencoding(), errors="replace")
                    chunks.append(decoded)
                    lines_seen += 1

                out = "".join(chunks)
                code = proc.returncode or 0
                if code == 0:
                    return ToolResult(call_id="", result=out, metadata={"exit_code": code})
                return ToolResult(call_id="", error=out or f"Exit {code}", metadata={"exit_code": code})

            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(call_id="", error=header + f"Timed out after {timeout}s")

            text = ""
            if stdout:
                try:
                    text = stdout.decode("utf-8")
                except Exception:
                    text = stdout.decode(sys.getdefaultencoding(), errors="replace")

            code = proc.returncode or 0
            if code == 0:
                return ToolResult(call_id="", result=header + (text or "Command executed successfully"))
            else:
                return ToolResult(call_id="", error=header + (text or f"Command failed (exit {code})"))

        except Exception as e:
            return ToolResult(call_id="", error=f"Shell execution error: {e}")
