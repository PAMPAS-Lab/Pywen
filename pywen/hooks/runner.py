from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import Any, Dict, Optional


class HookResult:
    def __init__(
        self,
        exit_code: int,
        stdout: str,
        stderr: str,
        json_out: Optional[Dict[str, Any]] = None,
    ):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.json_out = json_out

def run_command_hook(
    cmd: str,
    payload: Dict[str, Any],
    timeout: Optional[int],
) -> HookResult:
    env = os.environ.copy()
    shell_cmd = cmd if os.name == "posix" else f'cmd /S /C "{cmd}"'

    proc = subprocess.Popen(
        shell_cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(
            input=json.dumps(payload),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        return HookResult(exit_code=124, stdout="", stderr=f"Hook timed out: {cmd}")

    json_out = None
    try:
        json_out = json.loads(stdout.strip()) if stdout.strip().startswith("{") else None
    except json.JSONDecodeError:
        json_out = None

    return HookResult(proc.returncode, stdout, stderr, json_out)

async def run_command_hook_async(
    cmd: str,
    payload: Dict[str, Any],
    timeout: Optional[int],
) -> HookResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run_command_hook, cmd, payload, timeout)
