from __future__ import annotations
import importlib, pkgutil
from typing import Dict, Iterable, Set, Type, Optional, List
from dataclasses import dataclass
from pywen.tools.base_tool import BaseTool, ToolRiskLevel

@dataclass
class ToolEntry:
    instance: BaseTool
    providers: Set[str]
    risk: ToolRiskLevel = ToolRiskLevel.SAFE
    enabled: bool = True

TOOL_REGISTRY: Dict[str, ToolEntry] = {}

def register_tool(*, name: str, providers: Iterable[str] | str = '*', enabled: bool = True):
    def deco(cls: Type[BaseTool]):
        if not issubclass(cls, BaseTool):
            raise TypeError("@register_tool must decorate BaseTool subclasses")
        provs = {'*'} if providers == '*' else set(providers)
        tool = cls()
        tool.name = name
        if name in TOOL_REGISTRY:
            raise ValueError(f"Duplicate tool registration: {name}")
        TOOL_REGISTRY[name] = ToolEntry(
            instance=tool,
            providers=provs,
            risk=tool.risk_level,
            enabled=enabled,
        )
        return cls
    return deco

def get_tool(name: str) -> BaseTool:
    return TOOL_REGISTRY[name].instance

def list_tools_for_provider(provider: str,
                            allowlist: Optional[Iterable[str]] = None,
                            safe_mode: bool = False,
                            ) -> List[BaseTool]:
    allowset = set(allowlist) if allowlist else None
    out: List[BaseTool] = []
    for name, entry in TOOL_REGISTRY.items():
        if '*' not in entry.providers and provider not in entry.providers:
            continue
        if allowset and name not in allowset:
            continue
        if safe_mode and entry.risk != ToolRiskLevel.SAFE:
            continue
        out.append(entry.instance)
    return out


def tools_autodiscover(package: str = "pywen.tools"):
    pkg = importlib.import_module(package)
    for _, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
        if ispkg:
            tools_autodiscover(f"{package}.{modname}")
            continue
        if modname in {"base_tool",}:
            continue
        importlib.import_module(f"{package}.{modname}")
