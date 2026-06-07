from __future__ import annotations

import asyncio
import base64
import contextlib
import fnmatch
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from pywen.config.manager import ConfigManager
from pywen.llm.llm_basics import ToolCallResult, ToolCallResultDisplay
from pywen.tools.base_tool import BaseTool, ToolRiskLevel
from pywen.tools.tool_manager import register_instance


def _make_tool_result(
    call_id: str,
    message: str,
    *,
    is_error: bool = False,
    summary: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    display_markdown: Optional[str] = None,
) -> ToolCallResult:
    display = ToolCallResultDisplay(
        markdown=display_markdown if display_markdown is not None else message,
        summary=summary or ""
    )
    return ToolCallResult(
        call_id=call_id,
        result=None if is_error else message,
        error=message if is_error else None,
        display=display,
        metadata=metadata or {},
        timestamp=datetime.now(),
        summary=summary
    )

class MCPServerLaunchError(RuntimeError):
    pass

def _is_executable(cmd: str) -> bool:
    if os.path.sep in cmd or (os.path.altsep and os.path.altsep in cmd):
        return os.path.isfile(cmd) and os.access(cmd, os.X_OK)
    return shutil.which(cmd) is not None

class MCPServerManager:
    """
    - 启动/维护多个 MCP stdio server
    - 暴露 list_tools / call_tool
    - 统一关闭（可多次调用、并发安全）
    """
    def __init__(self) -> None:
        self._sessions: Dict[str, ClientSession] = {}
        self._ctxs: Dict[str, Any] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._stops: Dict[str, asyncio.Event] = {}
        self._ready: Dict[str, asyncio.Event] = {}
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def add_http_server(self, name: str, command: str) -> None:
        if name in self._sessions:
            return
        self._locks.setdefault(name, asyncio.Lock())
        async with self._locks[name]:
            if name in self._sessions:
                return

            stop = asyncio.Event()
            self._stops[name] = stop

            async def _owner():
                ctx = streamablehttp_client(command)
                self._ctxs[name] = ctx
                async with ctx as (read, write, _), ClientSession(read, write) as sess:
                    await sess.initialize()
                    self._sessions[name] = sess
                    self._ready[name].set()
                    await stop.wait()
                self._sessions.pop(name, None)
                self._ctxs.pop(name, None)

            self._ready[name] = asyncio.Event()
            task = asyncio.create_task(_owner())
            self._tasks[name] = task

            await asyncio.wait_for(self._ready[name].wait(), timeout=30.0)

    async def add_stdio_server(self, name: str, command: str, args: Iterable[str], *, timeout: float = 30.0) -> None:
        """
        启动并连接一个以 stdio 暴露的 MCP server。
        幂等：重复调用同名 server 不会重复启动。
        """
        if self._closed:
            raise MCPServerLaunchError("MCPServerManager is closed.")

        if name in self._sessions:
            return

        if not _is_executable(command):
            raise MCPServerLaunchError(
                f"Command '{command}' not found or not executable. Please install or fix PATH."
            )

        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            if name in self._sessions:
                return

            stop_evt = asyncio.Event()
            ready_evt = asyncio.Event()
            self._stops[name] = stop_evt
            self._ready[name] = ready_evt

            task = asyncio.create_task(
                self._owner_task(name, command, list(args), ready_evt, stop_evt),
                name=f"mcp-owner::{name}"
            )
            self._tasks[name] = task

            try:
                await asyncio.wait_for(ready_evt.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                task.cancel()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await task
                self._tasks.pop(name, None)
                self._stops.pop(name, None)
                self._ready.pop(name, None)
                raise MCPServerLaunchError(
                    f"Timed out waiting for MCP server '{name}' to become ready (timeout={timeout}s)."
                ) from None

            if task.done() and task.exception():
                ex = task.exception()
                self._tasks.pop(name, None)
                self._stops.pop(name, None)
                self._ready.pop(name, None)
                raise MCPServerLaunchError(
                    f"Failed to start MCP server '{name}': {ex}"
                )

    async def _owner_task(
        self,
        name: str,
        command: str,
        args: List[str],
        ready_evt: asyncio.Event,
        stop_evt: asyncio.Event,
    ):
        params = StdioServerParameters(command=command, args=args)
        ctx = stdio_client(params)
        try:
            async with ctx as (read, write), ClientSession(read, write) as sess:
                await sess.initialize()
                self._ctxs[name] = ctx
                self._sessions[name] = sess
                ready_evt.set()
                await stop_evt.wait()
        finally:
            self._sessions.pop(name, None)
            self._ctxs.pop(name, None)

    async def list_tools(self, server: str):
        sess = self._sessions.get(server)
        if not sess:
            raise MCPServerLaunchError(f"MCP server '{server}' is not ready.")
        return await sess.list_tools()

    async def call_tool(self, server: str, tool_name: str, args: Dict[str, Any]):
        sess = self._sessions.get(server)
        if not sess:
            raise MCPServerLaunchError(f"MCP server '{server}' is not ready.")
        return await sess.call_tool(tool_name, args or {})

    async def close(self, *, timeout: float = 10.0) -> None:
        if self._closed:
            return
        async with self._close_lock:
            if self._closed:
                return

            names = list(self._tasks.keys())
            for n in names:
                evt = self._stops.get(n)
                if evt and not evt.is_set():
                    evt.set()

            for n in names:
                task = self._tasks.get(n)
                if not task:
                    continue
                try:
                    await asyncio.wait_for(task, timeout=timeout)
                except asyncio.TimeoutError:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                except Exception:
                    pass

            for _, ctx in list(self._ctxs.items()):
                with contextlib.suppress(Exception):
                    await ctx.__aexit__(None, None, None)

            self._sessions.clear()
            self._ctxs.clear()
            self._tasks.clear()
            self._stops.clear()
            self._ready.clear()
            self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

@dataclass
class _RemoteSpec:
    """缓存远端工具的描述，用于构造本地工具的声明。"""
    name: str
    description: str
    input_schema: Dict[str, Any]

class MCPRemoteTool(BaseTool):
    """
    将 MCP server 上的某个具体工具包装为本地工具：
    - execute() 内部调用远端 server 的 tool
    - build() 生成 LLM 可消费的函数/工具声明（按 provider 适配）
    """
    def __init__(
        self,
        *,
        server: str,
        manager: MCPServerManager,
        spec: _RemoteSpec,
        display_name: Optional[str] = None,
        save_images_dir: Optional[str] = None,
        risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM,
        providers: Optional[Iterable[str]] = None,  # 仅用于注册可见性
    ) -> None:
        # BaseTool 基本字段
        self.name = spec.name
        self.display_name = display_name or spec.name
        self.description = spec.description or f"MCP tool '{spec.name}' from '{server}'."
        self.parameter_schema = spec.input_schema or {"type": "object", "properties": {}}
        self.risk_level = risk_level

        self._server = server
        self._manager = manager
        self._save_images_dir = save_images_dir
        self._providers = set(providers or {"*"})

    async def execute(self, **kwargs) -> ToolCallResult:
        call_id = kwargs.pop("call_id", None) or f"mcp::{self._server}::{self.name}"
        try:
            res = await self._manager.call_tool(self._server, self.name, kwargs or {})
        except Exception as e:
            return _make_tool_result(
                call_id=call_id,
                message=f"[MCP CALL ERROR] {e}",
                is_error=True,
                metadata={"server": self._server, "tool": self.name},
            )

        parts: List[str] = []
        is_err = bool(getattr(res, "isError", False))
        content = getattr(res, "content", []) or []

        if is_err:
            parts.append("[MCP ERROR]")

        for item in content:
            t = getattr(item, "type", "") or (item.get("type", "") if isinstance(item, dict) else "")
            if t == "text":
                txt = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else "") or ""
                parts.append(txt)
            elif t in ("image", "blob", "binary", "resource"):
                b64 = (
                    getattr(item, "data", None)
                    or getattr(item, "base64_data", None)
                    or (item.get("data") if isinstance(item, dict) else None)
                    or (item.get("base64_data") if isinstance(item, dict) else None)
                )
                mime = (
                    getattr(item, "mimeType", None)
                    or (item.get("mimeType") if isinstance(item, dict) else None)
                    or "application/octet-stream"
                )
                if self._save_images_dir and b64:
                    os.makedirs(self._save_images_dir, exist_ok=True)
                    ext = _guess_ext_from_mime(mime)
                    path = os.path.join(
                        self._save_images_dir,
                        f"mcp_{self._server}_{self.name}_{abs(hash(b64)) % 10_000_000}{ext}"
                    )
                    try:
                        raw = base64.b64decode(b64)
                        with open(path, "wb") as f:
                            f.write(raw)
                        parts.append(f"[{t} saved: {path}]")
                    except Exception as de:
                        parts.append(f"[{t} decode failed: {de}]")
                else:
                    parts.append(f"[{t} {mime} base64 omitted]")
            else:
                try:
                    parts.append(json.dumps(_safe_to_dict(item), ensure_ascii=False))
                except Exception:
                    parts.append(str(item))

        text = "\n".join([p for p in parts if p]).strip() or "(no content)"
        return _make_tool_result(
            call_id=call_id,
            message=text,
            is_error=is_err,
            metadata={"server": self._server, "tool": self.name},
            display_markdown=text,
        )

    def build(self, provider: str = "", func_type: str = "") -> Mapping[str, Any]:
        res = {}
        if provider.lower() in {"pywen", "codex", "openai"}:
            res = {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameter_schema
                }
            }
        elif provider.lower() in {"anthropic", "claude"}:
            res = {
                "name": self.name,
                "description": self.description,
                "input_schema": self.parameter_schema or {"type": "object", "properties": {}},
            }
        return res

    @property
    def providers(self) -> set[str]:
        return set(self._providers)

def _match_includes(name: str, patterns: Optional[List[str]]) -> bool:
    """include: ["browser_*", "files.read", "*"] -> 是否匹配。None/空表示不过滤。"""
    if not patterns:
        return True
    return any(fnmatch.fnmatch(name, p) for p in patterns)

def _guess_ext_from_mime(mime: str) -> str:
    mime = (mime or "").lower()
    if "png" in mime:
        return ".png"
    if "jpeg" in mime or "jpg" in mime:
        return ".jpg"
    if "gif" in mime:
        return ".gif"
    if "webp" in mime:
        return ".webp"
    if "svg" in mime:
        return ".svg"
    if "pdf" in mime:
        return ".pdf"
    return ".bin"

def _safe_to_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    out = {}
    for k in dir(obj):
        if k.startswith("_"):
            continue
        with contextlib.suppress(Exception):
            v = getattr(obj, k)
            if callable(v):
                continue
            out[k] = v
    return out

async def sync_mcp_servers(*, cfg_mgr: ConfigManager, overwrite: bool = True,) -> Tuple[MCPServerManager, List[str]]:
    """
    根据 config.mcp：
      - 启动 enabled 的 MCP servers
      - 拉取工具清单
      - 按 include 过滤
      - 将每个远端 tool 注册为本地工具
    返回：
      (MCPServerManager, 已注册工具名列表)
    """
    mcp_cfg = cfg_mgr.get_app_config().mcp 
    if not mcp_cfg or not mcp_cfg.enabled:
        return MCPServerManager(), []

    mcp_mgr = MCPServerManager()
    registered: List[str] = []

    servers = mcp_cfg.servers or []
    for srv in servers:
        if not srv.enabled:
            continue

        name: str = srv.name
        command: str = srv.command
        args: List[str] = srv.args or []
        include: List[str] = srv.include or []
        save_dir: Optional[str] = srv.save_images_dir or None

        if mcp_cfg.isolated and srv.isolated and "--isolated" not in args:
            args.append("--isolated")

        # 1. 启动 server, 默认使用 stdio
        if srv.type == "http":
            await mcp_mgr.add_http_server(name, command)
        else:
            await mcp_mgr.add_stdio_server(name, command, args)

        # 2. 拉取工具清单
        desc = await mcp_mgr.list_tools(name)
        tools = getattr(desc, "tools", None) or []

        for t in tools:
            tool_name = getattr(t, "name", None)
            if not tool_name or not _match_includes(tool_name, include):
                continue

            input_schema = (
                getattr(t, "input_schema", None)
                or getattr(t, "inputSchema", None)
                or {"type": "object", "properties": {}}
            )
            description = getattr(t, "description", "") or ""

            local_tool = MCPRemoteTool(
                server=name,
                manager=mcp_mgr,
                spec=_RemoteSpec(
                    name=tool_name,
                    description=description,
                    input_schema=input_schema,
                ),
                save_images_dir=save_dir,
                risk_level=ToolRiskLevel.MEDIUM,
            )

            register_instance(
                name=local_tool.name,
                instance=local_tool,
                overwrite=overwrite,
            )
            registered.append(local_tool.name)

    return mcp_mgr, registered
