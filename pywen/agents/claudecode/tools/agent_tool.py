"""
Agent Tool - Launch a new sub-agent task
Based on claude_code_version/tools/AgentTool/AgentTool.tsx
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from pywen.tools.base import BaseTool
from pywen.utils.tool_basics import ToolResult
from pywen.utils.llm_basics import LLMMessage

logger = logging.getLogger(__name__)


class AgentTool(BaseTool):
    """
    Agent Tool for launching sub-agent tasks
    Implements the AgentTool pattern from original Claude Code
    """
    
    def __init__(self, config=None):
        super().__init__(
            name="agent_tool",
            display_name="Task Agent",
            description="Launch a new agent that can perform complex tasks using available tools. Use this when you need to search for keywords, analyze code patterns, or perform multi-step operations that would benefit from focused sub-agent execution.",
            parameter_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The detailed task for the agent to perform. Be specific about what information you need back."
                    }
                },
                "required": ["prompt"]
            },
            is_output_markdown=True,
            can_update_output=False,
            config=config
        )
        self._agent_registry = None
    
    def set_agent_registry(self, agent_registry):
        """Set the agent registry for creating sub-agents"""
        self._agent_registry = agent_registry
    
    def is_risky(self, **kwargs) -> bool:
        """Agent tool is generally safe as it uses restricted tools"""
        return False
    
    async def execute(self, prompt: str, **kwargs) -> ToolResult:
        """
        Execute the agent tool by launching a sub-agent
        """
        try:
            if not self._agent_registry:
                return ToolResult(
                    success=False,
                    content="Agent registry not available. Cannot launch sub-agent.",
                    metadata={"error": "no_agent_registry"}
                )
            
            start_time = time.time()
            
            # Get the current agent (Claude Code Agent)
            current_agent = self._agent_registry.get_current_agent()
            if not current_agent or current_agent.type != "ClaudeCodeAgent":
                return ToolResult(
                    success=False,
                    content="Agent tool can only be used with Claude Code Agent",
                    metadata={"error": "invalid_agent_type"}
                )
            
            # Create sub-agent with restricted tools
            sub_agent = await self._create_sub_agent(current_agent)
            
            # Execute sub-agent task
            result_parts = []
            tool_use_count = 0
            
            try:
                # Run the sub-agent with the given prompt
                async for event in sub_agent._query_recursive(
                    messages=[
                        LLMMessage(role="system", content=self._get_agent_system_prompt()),
                        LLMMessage(role="user", content=prompt)
                    ],
                    system_prompt=self._get_agent_system_prompt(),
                    max_iterations=5  # Limit iterations for sub-agent
                ):
                    if event["type"] == "content":
                        result_parts.append(event["content"])
                    elif event["type"] == "tool_call":
                        tool_use_count += 1
                    elif event["type"] in ["final", "error"]:
                        if event.get("content"):
                            result_parts.append(event["content"])
                        break
                
                # Combine results
                final_result = "".join(result_parts).strip()
                if not final_result:
                    final_result = "Sub-agent completed but returned no output."
                
                # Add execution summary
                duration = time.time() - start_time
                summary = f"\n\n---\nAgent execution summary: {tool_use_count} tool uses, {duration:.1f}s"
                
                return ToolResult(
                    success=True,
                    content=final_result + summary,
                    metadata={
                        "tool_use_count": tool_use_count,
                        "duration": duration,
                        "agent_type": "sub_agent"
                    }
                )
                
            except Exception as e:
                logger.error(f"Sub-agent execution failed: {e}")
                return ToolResult(
                    success=False,
                    content=f"Sub-agent execution failed: {str(e)}",
                    metadata={"error": "sub_agent_execution_failed"}
                )
                
        except Exception as e:
            logger.error(f"Agent tool execution failed: {e}")
            return ToolResult(
                success=False,
                content=f"Agent tool failed: {str(e)}",
                metadata={"error": "agent_tool_failed"}
            )
    
    async def _create_sub_agent(self, parent_agent):
        """Create a sub-agent with restricted tools"""
        # Import here to avoid circular imports
        from pywen.agents.claudecode.claude_code_agent import ClaudeCodeAgent
        
        # Create sub-agent instance
        sub_agent = ClaudeCodeAgent(parent_agent.config, parent_agent.cli_console)
        
        # Set restricted tools (read-only + some write tools, but no recursive agents)
        allowed_tools = self._get_agent_tools(parent_agent.tools)
        sub_agent.tools = allowed_tools
        
        # Copy context
        sub_agent.project_path = parent_agent.project_path
        sub_agent.context = parent_agent.context.copy()
        
        return sub_agent
    
    def _get_agent_tools(self, parent_tools: List[BaseTool]) -> List[BaseTool]:
        """Get allowed tools for sub-agent (no recursive agents)"""
        allowed_tool_names = {
            'read_file', 'read_many_files', 'write_file', 'edit_file',
            'ls', 'grep', 'glob', 'bash', 'web_fetch', 'web_search',
            'memory_read', 'memory_write'
        }
        
        # Filter tools and exclude recursive sub-agents
        return [
            tool for tool in parent_tools
            if (tool.name in allowed_tool_names and 
                tool.name not in ['agent_tool', 'architect_tool'])
        ]
    
    def _get_agent_system_prompt(self) -> str:
        """Get system prompt for sub-agent"""
        return """You are a focused sub-agent for Claude Code. Your role is to complete specific tasks efficiently and return concise results.

## Guidelines for Sub-Agent Tasks
- Be extremely concise and focused on the specific task
- Use tools efficiently and in parallel when possible
- Return absolute file paths when referencing files
- Provide structured, actionable results
- Avoid unnecessary explanations unless specifically requested
- Complete the task and return results quickly

## Tool Usage
- You can use multiple tools concurrently in a single response
- Focus on read-only operations when possible for analysis tasks
- Be precise with file operations and command execution

## Important Notes
- This is a sub-agent execution - be direct and task-focused
- Your response will be returned to the parent agent
- Provide clear, actionable information that directly addresses the task"""
