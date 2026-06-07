from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Type

from pywen.cli.cli_console import CLIConsole
from pywen.hooks.manager import HookManager
from pywen.hooks.models import HookEvent
from pywen.tools.base_tool import BaseTool, ToolRiskLevel
from pywen.utils.permission_manager import PermissionManager


@dataclass
class ToolEntry:
    instance: BaseTool
    providers: Set[str]
    risk: ToolRiskLevel = ToolRiskLevel.SAFE
    enabled: bool = True

TOOL_REGISTRY: Dict[str, ToolEntry] = {}

def register_instance(
    *,
    name: str,
    instance: BaseTool,
    providers: Iterable[str] | str = "*",
    enabled: bool = True,
    overwrite: bool = False,
) -> None:
    """
    运行时注册一个已经实例化好的 BaseTool。
    - name: 工具在注册表中的唯一名（LLM可见名）
    - providers: 可见 provider 白名单；"*" 表示所有
    - overwrite=True 允许覆盖已有同名工具（热替换）
    """
    if not isinstance(instance, BaseTool):
        raise TypeError("register_instance: 'instance' must be BaseTool")

    if not name:
        raise ValueError("register_instance: 'name' is required")

    if name in TOOL_REGISTRY and not overwrite:
        raise ValueError(f"register_instance: duplicate tool name '{name}' (use overwrite=True to replace)")

    provs = {"*"} if providers == "*" else set(providers)
    risk = getattr(instance, "risk_level", ToolRiskLevel.SAFE)

    TOOL_REGISTRY[name] = ToolEntry(
        instance=instance,
        providers=provs,
        risk=risk,
        enabled=enabled,
    )

def unregister_tool(name: str) -> bool:
    """卸载工具；返回是否确实删除了某项。"""
    return TOOL_REGISTRY.pop(name, None) is not None

def is_registered(name: str) -> bool:
    return name in TOOL_REGISTRY

def list_tool_names() -> List[str]:
    return list(TOOL_REGISTRY.keys())

def get_entry(name: str) -> ToolEntry:
    return TOOL_REGISTRY[name]

def replace_instance(name: str, instance: BaseTool) -> None:
    """在不改变 providers / flags 前提下，仅替换实例（热更新实现细节）。"""
    if name not in TOOL_REGISTRY:
        raise KeyError(f"replace_instance: tool '{name}' not found")
    entry = TOOL_REGISTRY[name]
    TOOL_REGISTRY[name] = ToolEntry(
        instance=instance,
        providers=entry.providers,
        risk=getattr(instance, "risk_level", entry.risk),
        enabled=entry.enabled,
    )

def register_tool(*, name: str, providers: Iterable[str] | str = '*', enabled: bool = True):
    """
    用于“静态工具”的类级注册：import 时无参实例化并注册。
    """
    def deco(cls: Type[BaseTool]):
        if not issubclass(cls, BaseTool):
            raise TypeError("@register_tool must decorate BaseTool subclasses")
        tool = cls()
        tool.name = name

        register_instance(
            name=name,
            instance=tool,
            providers=providers,
            enabled=enabled,
            overwrite=False,
        )
        return cls
    return deco

class ToolManager:
    def __init__(
        self,
        perm_mgr: PermissionManager | None = None,
        hook_mgr: HookManager | None = None,
        cli: CLIConsole | None = None,
    ):
        self.perm_mgr = perm_mgr
        self.hook_mgr = hook_mgr
        self.cli = cli

    @staticmethod
    def autodiscover(package: str = "pywen.tools") -> None:
        """
        导入模块时执行类装饰器注册。
        动态工具请在运行时调用 register_instance()，无需放到这个扫描流程。
        """
        pkg = importlib.import_module(package)
        for _, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
            if ispkg:
                ToolManager.autodiscover(f"{package}.{modname}")
                continue
            if modname in {"base_tool", "tool_manager", "mcp_tool"}:
                continue
            importlib.import_module(f"{package}.{modname}")

    @staticmethod
    def get_tool(name: str) -> BaseTool:
        entry = TOOL_REGISTRY.get(name)
        if not entry:
            raise KeyError(f"Tool '{name}' not found")
        if not entry.enabled:
            raise RuntimeError(f"Tool '{name}' is registered but disabled")
        return entry.instance

    @staticmethod
    def list_for_provider(provider: str, allowlist: Optional[Iterable[str]] = None, safe_mode: bool = False,) -> List[BaseTool]:
        allowset = set(allowlist) if allowlist else None
        out: List[BaseTool] = []
        for name, entry in TOOL_REGISTRY.items():
            if not entry.enabled:
                continue
            if '*' not in entry.providers and provider not in entry.providers:
                continue
            if allowset and name not in allowset:
                continue
            if safe_mode and entry.risk != ToolRiskLevel.SAFE:
                continue
            out.append(entry.instance)
        return out

    async def execute(self, tool_name: str,  tool_args: Dict[str, Any], tool: BaseTool, **kwargs ) -> Tuple[bool, Optional[str | Dict]]:
        if self.hook_mgr:
            pre_ok, pre_msg, _ = await self.hook_mgr.emit(
                HookEvent.PreToolUse,
                base_payload={"session_id": ""},
                tool_name=tool_name,
                tool_input=tool_args,
            )
            if not pre_ok:
                blocked_reason = pre_msg or "Tool call blocked by PreToolUse hook"
                return False, blocked_reason

        if self.cli:
            is_approved = await self.cli.confirm_tool_call(tool_name, tool_args, tool)
            if not is_approved:
                return False, f"'{tool_name}' was rejected by the user."

        res = await tool.execute(**tool_args, **kwargs)

        if self.hook_mgr:
            post_ok, post_msg, _ = await self.hook_mgr.emit(
                HookEvent.PostToolUse,
                base_payload={"session_id": ""},
                tool_name=tool_name,
                tool_input=tool_args,
                tool_response={"result": res.result, "success": res.success, "error": res.error},
            )
            if not post_ok:
                reason = post_msg or "PostToolUse hook blocked further processing"
                res.error = reason
                res.result = None

        return res.success, res.result
