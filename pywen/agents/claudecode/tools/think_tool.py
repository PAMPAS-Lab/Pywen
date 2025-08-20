"""
Think Tool - Log thoughts and reasoning
Based on claude_code_version/tools/ThinkTool/ThinkTool.tsx
"""
import logging
from datetime import datetime
from typing import Any, Dict

from pywen.tools.base import BaseTool
from pywen.utils.tool_basics import ToolResult

logger = logging.getLogger(__name__)


class ThinkTool(BaseTool):
    """
    Think Tool for logging thoughts and reasoning
    Allows the AI to record its thinking process
    """
    
    def __init__(self, config=None):
        super().__init__(
            name="think",
            display_name="Think",
            description="Share your thoughts and reasoning process with the user. Use this to show your thinking, analysis, or decision-making process transparently.",
            parameter_schema={
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "Your thoughts, reasoning, or analysis"
                    }
                },
                "required": ["thought"]
            },
            is_output_markdown=False,
            can_update_output=False,
            config=config
        )
        self._thoughts_log = []
    
    def is_risky(self, **kwargs) -> bool:
        """Think tool is completely safe"""
        return False
    
    async def execute(self, thought: str, **kwargs) -> ToolResult:
        """
        Execute the think tool by logging the thought
        """
        try:
            # Log the thought with timestamp
            timestamp = datetime.now().isoformat()
            thought_entry = {
                "timestamp": timestamp,
                "thought": thought,
                "length": len(thought)
            }
            
            # Store in memory (could be extended to persist to file)
            self._thoughts_log.append(thought_entry)
            
            # Log for debugging/monitoring
            logger.info(f"Thought logged: {len(thought)} characters")
            
            # Format the thought for display
            formatted_thought = f"💭 **思考过程:**\n\n{thought}\n\n---\n*思考时间: {timestamp}*"

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
            logger.error(f"Think tool execution failed: {e}")
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
