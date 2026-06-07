from __future__ import annotations

import re
from typing import Optional


def matches_tool(matcher: Optional[str], tool_name: str) -> bool:
    if matcher is None or matcher == "" or matcher == "*":
        return True
    if not any(ch in matcher for ch in ".*+?|()[]{}\\|"):
        return matcher == tool_name
    return re.fullmatch(matcher, tool_name) is not None

