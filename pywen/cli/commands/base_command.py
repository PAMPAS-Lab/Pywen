"""基础命令类"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional

class CommandAction(str, Enum):
    FORWARD = "forward"   # 不处理，交给 agent 原始输入
    HANDLED = "handled"   # 已处理，本轮结束
    REWRITE = "rewrite"   # 改写输入，交给 agent 改写后的文本
    EXIT = "exit"         # 退出交互

@dataclass(frozen=True)
class CommandResult:
    action: CommandAction
    text: Optional[str] = None
    error: Optional[str] = None

class BaseCommand(ABC):
    """基础命令类"""
    def __init__(self, name: str, description: str, alt_name: Optional[str] = None):
        self.name = name
        self.description = description
        self.alt_name = alt_name
    
    @abstractmethod
    async def execute(self, context: Dict[str, Any], args: str) -> CommandResult:
        ...
