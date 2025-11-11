"""
Permission management system for Pywen tools.
Provides fine-grained control over tool execution permissions.
"""

from enum import Enum
from typing import Set, Dict, Any, Optional
from dataclasses import dataclass


class PermissionLevel(Enum):
    """Permission levels for tool execution."""
    LOCKED = "locked"           # 全锁状态：所有工具都需要确认
    EDIT_ONLY = "edit_only"     # 编辑权限：自动确认文件编辑，其他需要确认
    PLANNING = "planning"       # 规划权限：自动确认非编辑操作，编辑需要确认
    YOLO = "yolo"              # 锁开状态：自动确认所有操作


@dataclass
class PermissionRule:
    """Permission rule for specific tool categories."""
    tool_categories: Set[str]
    auto_approve: bool
    description: str


class PermissionManager:
    """Manages tool execution permissions based on permission levels."""
    
    def __init__(self, permission_level: PermissionLevel = PermissionLevel.LOCKED):
        self.permission_level = permission_level
        self._setup_tool_categories()
        self._setup_permission_rules()
    
    def _setup_tool_categories(self):
        """Define tool categories for permission management."""
        self.tool_categories = {
            # 文件编辑类工具
            "file_edit": {
                "write_file", "edit_file", "edit", "apply_patch"
            },
            
            # 文件读取类工具
            "file_read": {
                "read_file", "read_many_files"
            },
            
            # 文件系统浏览工具
            "file_system": {
                "ls", "grep", "glob", "find"
            },
            
            # 系统命令工具
            "system_command": {
                "bash", "shell", "cmd"
            },
            
            # 网络工具
            "network": {
                "web_fetch", "web_search", "curl", "wget"
            },
            
            # 内存和状态工具
            "memory": {
                "memory", "remember", "recall"
            },
            
            # 智能体工具
            "agent": {
                "agent_tool", "architect_tool", "sub_agent"
            },
            
            # Git 工具
            "git": {
                "git_status", "git_log", "git_diff", "git_commit", "git_push"
            }
        }
    
    def _setup_permission_rules(self):
        """Setup permission rules for each permission level."""
        self.permission_rules = {
            PermissionLevel.LOCKED: {
                # 全锁状态：所有工具都需要确认
                "file_edit": PermissionRule({"file_edit"}, False, "文件编辑需要确认"),
                "file_read": PermissionRule({"file_read"}, False, "文件读取需要确认"),
                "file_system": PermissionRule({"file_system"}, False, "文件系统操作需要确认"),
                "system_command": PermissionRule({"system_command"}, False, "系统命令需要确认"),
                "network": PermissionRule({"network"}, False, "网络操作需要确认"),
                "memory": PermissionRule({"memory"}, False, "内存操作需要确认"),
                "agent": PermissionRule({"agent"}, False, "智能体操作需要确认"),
                "git": PermissionRule({"git"}, False, "Git操作需要确认"),
            },
            
            PermissionLevel.EDIT_ONLY: {
                # 编辑权限：自动确认文件编辑，其他需要确认
                "file_edit": PermissionRule({"file_edit"}, True, "文件编辑自动确认"),
                "file_read": PermissionRule({"file_read"}, False, "文件读取需要确认"),
                "file_system": PermissionRule({"file_system"}, False, "文件系统操作需要确认"),
                "system_command": PermissionRule({"system_command"}, False, "系统命令需要确认"),
                "network": PermissionRule({"network"}, False, "网络操作需要确认"),
                "memory": PermissionRule({"memory"}, False, "内存操作需要确认"),
                "agent": PermissionRule({"agent"}, False, "智能体操作需要确认"),
                "git": PermissionRule({"git"}, False, "Git操作需要确认"),
            },
            
            PermissionLevel.PLANNING: {
                # 规划权限：自动确认非编辑操作，编辑需要确认
                "file_edit": PermissionRule({"file_edit"}, False, "文件编辑需要确认"),
                "file_read": PermissionRule({"file_read"}, True, "文件读取自动确认"),
                "file_system": PermissionRule({"file_system"}, True, "文件系统操作自动确认"),
                "system_command": PermissionRule({"system_command"}, True, "系统命令自动确认"),
                "network": PermissionRule({"network"}, True, "网络操作自动确认"),
                "memory": PermissionRule({"memory"}, True, "内存操作自动确认"),
                "agent": PermissionRule({"agent"}, True, "智能体操作自动确认"),
                "git": PermissionRule({"git"}, True, "Git操作自动确认"),
            },
            
            PermissionLevel.YOLO: {
                # 锁开状态：自动确认所有操作
                "file_edit": PermissionRule({"file_edit"}, True, "文件编辑自动确认"),
                "file_read": PermissionRule({"file_read"}, True, "文件读取自动确认"),
                "file_system": PermissionRule({"file_system"}, True, "文件系统操作自动确认"),
                "system_command": PermissionRule({"system_command"}, True, "系统命令自动确认"),
                "network": PermissionRule({"network"}, True, "网络操作自动确认"),
                "memory": PermissionRule({"memory"}, True, "内存操作自动确认"),
                "agent": PermissionRule({"agent"}, True, "智能体操作自动确认"),
                "git": PermissionRule({"git"}, True, "Git操作自动确认"),
            }
        }
    
    def get_tool_category(self, tool_name: str) -> Optional[str]:
        """Get the category of a tool."""
        for category, tools in self.tool_categories.items():
            if tool_name in tools:
                return category
        return None
    
    def should_auto_approve(self, tool_name: str, **kwargs) -> bool:
        """Determine if a tool should be auto-approved based on current permission level."""
        # Get tool category
        category = self.get_tool_category(tool_name)
        if not category:
            # Unknown tools default to requiring confirmation
            return False
        
        # Get permission rule for current level
        rules = self.permission_rules.get(self.permission_level, {})
        rule = rules.get(category)
        
        if not rule:
            # No rule found, default to requiring confirmation
            return False
        
        # Special handling for system commands based on danger level
        if category == "system_command" and rule.auto_approve:
            return self._is_safe_system_command(tool_name, **kwargs)
        
        return rule.auto_approve
    
    def _is_safe_system_command(self, tool_name: str, **kwargs) -> bool:
        """Check if a system command is safe for auto-approval."""
        if tool_name != "bash":
            return True
        
        command = kwargs.get("command", "")
        if not command:
            return True
        
        # High risk commands that should always require confirmation
        high_risk_commands = [
            "rm -rf", "del /s", "format", "fdisk", "mkfs", "dd", 
            "shutdown", "reboot", "halt", "poweroff"
        ]
        
        command_lower = command.lower()
        for risk_cmd in high_risk_commands:
            if risk_cmd in command_lower:
                return False
        
        return True
    
    def get_permission_description(self) -> str:
        """Get description of current permission level."""
        descriptions = {
            PermissionLevel.LOCKED: "🔒 全锁状态：所有操作都需要用户确认",
            PermissionLevel.EDIT_ONLY: "✏️ 编辑权限：自动确认文件编辑操作，其他需要确认",
            PermissionLevel.PLANNING: "🧠 规划权限：自动确认非编辑操作，文件编辑需要确认",
            PermissionLevel.YOLO: "🚀 锁开状态：自动确认所有操作"
        }
        return descriptions.get(self.permission_level, "未知权限级别")
    
    def set_permission_level(self, level: PermissionLevel):
        """Set permission level."""
        self.permission_level = level
    
    def get_permission_level(self) -> PermissionLevel:
        """Get current permission level."""
        return self.permission_level
    
    def get_available_levels(self) -> Dict[str, str]:
        """Get all available permission levels with descriptions."""
        return {
            "locked": "🔒 全锁状态：所有操作都需要用户确认",
            "edit_only": "✏️ 编辑权限：自动确认文件编辑操作，其他需要确认", 
            "planning": "🧠 规划权限：自动确认非编辑操作，文件编辑需要确认",
            "yolo": "🚀 锁开状态：自动确认所有操作"
        }
    
    def get_tool_permission_info(self, tool_name: str) -> Dict[str, Any]:
        """Get permission information for a specific tool."""
        category = self.get_tool_category(tool_name)
        auto_approve = self.should_auto_approve(tool_name)
        
        rules = self.permission_rules.get(self.permission_level, {})
        rule = rules.get(category) if category else None
        
        return {
            "tool_name": tool_name,
            "category": category or "unknown",
            "auto_approve": auto_approve,
            "permission_level": self.permission_level.value,
            "rule_description": rule.description if rule else "未知工具类型，需要确认"
        }
