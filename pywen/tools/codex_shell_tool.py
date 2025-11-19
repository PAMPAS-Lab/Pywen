import asyncio
import os
import shlex
from typing import Any, Dict, List, Optional, override,Mapping
from .base import BaseTool, ToolResult, ToolRiskLevel

def _assert_command_list(command: Any) -> List[str]:
    if not (isinstance(command, list) and all(isinstance(x, str) for x in command)):
        raise ValueError("`command` must be a list[str]")
    return command

def _join_cmd(command: List[str]) -> str:
    return " ".join(shlex.quote(x) for x in command)

class CodexShellTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="shell",
            display_name="Codex Shell",
            description="Runs a shell command and returns its output.",
            parameter_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The command to execute (argv array), e.g. ['ls','-la'] "
                                       "If you need shell features, pass ['bash','-lc','your pipeline...']",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "The working directory to execute the command in",
                    },
                    "timeout_ms": {
                        "type": "number",
                        "description": "The timeout for the command in milliseconds",
                    },
                    "with_escalated_permissions": {
                        "type": "boolean",
                        "description": (
                            "Whether to request escalated permissions. "
                            "Set to true if command needs to be run without sandbox restrictions"
                        ),
                    },
                    "justification": {
                        "type": "string",
                        "description": (
                            "Only set if with_escalated_permissions is true. "
                            "1-sentence explanation of why we want to run this command."
                        ),
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.LOW,
        )

    def validate_parameters(self, **kwargs) -> bool:
        try:
            _assert_command_list(kwargs.get("command"))
        except Exception:
            return False
        if kwargs.get("with_escalated_permissions") and not kwargs.get("justification"):
            return False
        return True

    def get_risk_level(self, **kwargs) -> ToolRiskLevel:
        try:
            cmd_list = _assert_command_list(kwargs.get("command"))
        except Exception:
            return ToolRiskLevel.MEDIUM
        cmd_str = f" {_join_cmd(cmd_list)} "

        high = [" rm -rf", " fdisk", " mkfs", " dd ", " shutdown", " reboot", " :> "]
        if any(tok in cmd_str for tok in high):
            return ToolRiskLevel.HIGH

        medium = [" rm ", " mv ", " cp ", " chmod", " chown", " sudo", " su "]
        if any(tok in cmd_str for tok in medium):
            return ToolRiskLevel.MEDIUM

        return ToolRiskLevel.LOW

    @override
    async def _generate_confirmation_message(self, **kwargs) -> str:
        cmd_list = _assert_command_list(kwargs.get("command"))
        cmd_str = _join_cmd(cmd_list)
        workdir: str = kwargs.get("workdir") or os.getcwd()
        timeout_ms = kwargs.get("timeout_ms")
        rl = self.get_risk_level(**kwargs).value.upper()

        bits = [
            f"command(list): {cmd_list}",
            f"command(str):  {cmd_str}",
            f"workdir:       {workdir}",
        ]
        if timeout_ms is not None:
            bits.append(f"timeout_ms:   {int(timeout_ms)}")
        if kwargs.get("with_escalated_permissions"):
            bits.append("escalated:     true")
            if kwargs.get("justification"):
                bits.append(f"justification: {kwargs['justification']}")

        msg = "Execute Codex Shell:\n" + "\n".join(bits) + f"\nRisk Level: {rl}"
        if rl == "HIGH":
            msg += "\n⚠️  WARNING: HIGH RISK command may cause system damage!"
        elif rl == "MEDIUM":
            msg += "\n⚠️  CAUTION: This command may modify files or system state."
        return msg

    async def execute(self, **kwargs) -> ToolResult:
        try:
            command = _assert_command_list(kwargs.get("command"))
        except Exception as e:
            return ToolResult(call_id="", error=str(e))

        if kwargs.get("with_escalated_permissions") and not kwargs.get("justification"):
            return ToolResult(call_id="", error="`justification` is required when `with_escalated_permissions` is true")

        workdir: Optional[str] = kwargs.get("workdir") or None
        timeout_ms = kwargs.get("timeout_ms")
        timeout_s: Optional[float] = None if timeout_ms is None else float(timeout_ms) / 1000.0

        header = f"$ {_join_cmd(command)}\n"

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=workdir or None,
                env=os.environ.copy(),
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(call_id="", error=header + f"Timed out after {int(timeout_s or 0)}s")

            text = (stdout or b"").decode("utf-8", errors="replace")
            code = proc.returncode or 0
            if code == 0:
                return ToolResult(call_id="", result=header + (text or "Command executed successfully"),
                                  metadata={"exit_code": code})
            else:
                return ToolResult(call_id="", error=header + (text or f"Command failed (exit {code})"),
                                  metadata={"exit_code": code})

        except Exception as e:
            return ToolResult(call_id="", error=f"Shell execution error: {e}")

    def build(self) -> Mapping[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "strict": False,
            "parameters": self.parameter_schema,
        }

