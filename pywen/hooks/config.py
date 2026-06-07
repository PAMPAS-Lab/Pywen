from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .models import HookCommand, HookGroup, HooksConfig


def load_hooks_config(path: str | Path) -> HooksConfig:
    p = Path(path)
    if not p.exists():
        return HooksConfig()

    data: Dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    raw_hooks: Dict[str, List[Dict[str, Any]]] = data.get("hooks", {})

    parsed: Dict[str, List[HookGroup]] = {}

    for event_name, groups in raw_hooks.items():
        group_objs: List[HookGroup] = []
        for g in groups:
            matcher = g.get("matcher")
            hooks = []
            for h in g.get("hooks", []):
                if h.get("type") != "command":
                    continue
                hooks.append(
                    HookCommand(
                        type="command",
                        command=h["command"],
                        timeout=h.get("timeout"),
                    )
                )
            group_objs.append(HookGroup(matcher=matcher, hooks=hooks))
        parsed[event_name] = group_objs

    return HooksConfig(hooks=parsed)
