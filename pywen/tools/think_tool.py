"""
Think Tool - Log thoughts and reasoning
Based on claude_code_version/tools/ThinkTool/ThinkTool.tsx
"""
from datetime import datetime
from typing import Any, Mapping 
from pywen.tools.base_tool import BaseTool
from pywen.utils.tool_basics import ToolResult
from pywen.core.tool_registry2 import register_tool

DESCRIPTION= """Use the tool to think about something. 
It will not obtain new information or make any changes to the repository, 
but just log the thought. Use it when complex reasoning or brainstorming is needed. 

Common use cases:
1. When exploring a repository and discovering the source of a bug, 
call this tool to brainstorm several unique ways of fixing the bug, 
and assess which change(s) are likely to be simplest and most effective
2. After receiving test results, use this tool to brainstorm ways to fix failing tests
3. When planning a complex refactoring, use this tool to outline different approaches and their tradeoffs
4. When designing a new feature, use this tool to think through architecture decisions and implementation details
5. When debugging a complex issue, use this tool to organize your thoughts and hypotheses

The tool simply logs your thought process for better transparency and does not execute any code or make changes.
"""

@register_tool(name="think_tool", providers=["claude"]) 
class ThinkTool(BaseTool):
    name="think_tool"
    display_name="Think"
    description=DESCRIPTION
    parameter_schema={
        "type": "object",
        "properties": {
            "thought": {
                "type": "string",
                "description": "Your thoughts, reasoning, or analysis"
                }
        },
        "required": ["thought"]
    }
    _thoughts_log = []
    
    def is_risky(self, **kwargs) -> bool:
        """Think tool is completely safe"""
        return False
    
    async def execute(self, **kwargs) -> ToolResult:
        thought = kwargs.get('thought', '')
        try:
            timestamp = datetime.now().isoformat()
            thought_entry = {
                "timestamp": timestamp,
                "thought": thought,
                "length": len(thought)
            }
            
            self._thoughts_log.append(thought_entry)

            formatted_thought = f"**thinking**\n\n{thought}\n"

            return ToolResult(
                call_id="think",
                result=formatted_thought,
                metadata={
                    "thought_length": len(thought),
                    "timestamp": timestamp,
                    "total_thoughts": len(self._thoughts_log)
                }
            )
            
        except Exception as e:
            return ToolResult(
                call_id="think",
                error=f"Failed to log thought: {str(e)}",
                metadata={"error": "think_tool_failed"}
            )
    
    def get_thoughts_log(self) -> list:
        """Get all logged thoughts"""
        return self._thoughts_log.copy()
    
    def clear_thoughts_log(self):
        """Clear the thoughts log"""
        self._thoughts_log.clear()
    
    def get_recent_thoughts(self, count: int = 5) -> list:
        """Get the most recent thoughts"""
        return self._thoughts_log[-count:] if self._thoughts_log else []

    def build(self, provider:str = "", func_type: str = "") -> Mapping[str, Any]:
        """ claude 专用 """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameter_schema,
        }
