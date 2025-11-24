import logging
import time
from typing import List, Mapping,Any
from pywen.tools.base_tool import BaseTool
from pywen.utils.tool_basics import ToolResult
from pywen.utils.llm_basics import LLMMessage
from pywen.core.tool_registry2 import register_tool

logger = logging.getLogger(__name__)

DESCRIPTION = """
Your go-to tool for any technical or coding task. 
Analyzes requirements and breaks them down into clear, 
actionable implementation steps. 
Use this whenever you need help planning how to implement a feature, 
solve a technical problem, or structure your code.
"""

ARCHITECT_SYSTEM_PROMPT = """You are an expert software architect. 
Your role is to analyze technical requirements and produce clear, actionable implementation plans.
These plans will then be carried out by a junior software engineer so you need to be specific and detailed. 
However do not actually write the code, just explain the plan.

Follow these steps for each request:
1. Carefully analyze requirements to identify core functionality and constraints
2. Define clear technical approach with specific technologies and patterns
3. Break down implementation into concrete, actionable steps at the appropriate level of abstraction

Keep responses focused, specific and actionable.

IMPORTANT: Do not ask the user if you should implement the changes at the end. 
Just provide the plan as described above.
IMPORTANT: Do not attempt to write the code or use any string modification tools. Just provide the plan.

## Available Tools
You have access to read-only tools for code exploration and analysis:
- File reading and searching tools
- Directory listing and globbing
- Web search for research

Use these tools to understand the existing codebase before providing your analysis and recommendations.
"""

@register_tool(name = "architect_tool", providers=["claude"])
class ArchitectTool(BaseTool):
    name="architect_tool"
    display_name="Architect"
    description= DESCRIPTION
    parameter_schema={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The technical request or coding task to analyze"
            },
            "context": {
                "type": "string",
                "description": "Optional context from previous conversation or system state",
            "default": ""
            }
        },
        "required": ["prompt"]
    }
    
    def set_current_agent(self, agent):
        self.current_agent = agent
    
    def is_risky(self, **kwargs) -> bool:
        """Architect tool is read-only and safe"""
        return False
    
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the architect tool for technical analysis
        """
        prompt = kwargs.get('prompt', '')
        context = kwargs.get('context', '')
        
        try:
            start_time = time.time()
            if not self.current_agent or self.current_agent.type != "ClaudeAgent":
                return ToolResult(
                    call_id="architect_tool",
                    error="Architect tool can only be used with Claude Code Agent",
                    metadata={"error": "invalid_agent_type"}
                )
            architect_agent = await self._create_architect_agent(self.current_agent)
            content = f"<context>{context}</context>\n\n{prompt}" if context else prompt
            result_parts = ["🏗️ **Architect Analysis**\n\n"]
            result_parts.append("|_ Initializing architect agent...\n")
            tool_use_count = 0

            try:
                result_parts.append("|_ Starting analysis...\n\n")
                final_content = ""
                analysis_completed = False
                error_occurred = False

                async for event in architect_agent._query_recursive(
                    messages=[
                        LLMMessage(role="system", content=self._get_architect_system_prompt()),
                        LLMMessage(role="user", content=content)
                    ],
                    system_prompt=self._get_architect_system_prompt(),
                    max_iterations=3
                ):
                    event_type = event.get("type", "")

                    if event_type == "content":
                        content_text = event.get("content", "")
                        if content_text.strip():
                            result_parts.append(content_text)
                            final_content += content_text
                    elif event_type == "tool_call_start":
                        tool_data = event.get("data", {})
                        tool_name = tool_data.get("name", "unknown")
                        tool_args = tool_data.get("arguments", {})
                        
                        if tool_name == "read_file" and "file_path" in tool_args:
                            result_parts.append(f"|_ 📖 Reading file: {tool_args['file_path']}\n")
                        elif tool_name == "bash" and "command" in tool_args:
                            cmd = tool_args["command"][:50] + "..." if len(tool_args["command"]) > 50 else tool_args["command"]
                            result_parts.append(f"|_ 🔧 Running: {cmd}\n")
                        elif tool_name == "grep" and "pattern" in tool_args:
                            result_parts.append(f"|_ 🔍 Searching: {tool_args['pattern']}\n")
                        elif tool_name == "glob" and "pattern" in tool_args:
                            result_parts.append(f"|_ 📁 Finding files: {tool_args['pattern']}\n")
                        elif tool_name == "web_search" and "query" in tool_args:
                            result_parts.append(f"|_ 🌐 Web search: {tool_args['query']}\n")
                        elif tool_name == "web_fetch" and "url" in tool_args:
                            result_parts.append(f"|_ 🌐 Fetching: {tool_args['url']}\n")
                        else:
                            result_parts.append(f"|_ 🔧 Using {tool_name} tool\n")
                        
                        tool_use_count += 1
                    elif event_type == "tool_call_end":
                        tool_data = event.get("data", {})
                        tool_name = tool_data.get("name", "unknown")
                        success = tool_data.get("success", True)
                        
                        if success:
                            result_parts.append(f"|_ ✅ Completed {tool_name}\n")
                        else:
                            result_parts.append(f"|_ ❌ Failed {tool_name}\n")
                    elif event_type in ["final", "task_complete"]:
                        # Capture final content from these events
                        if event.get("content"):
                            final_event_content = event["content"]
                            result_parts.append(final_event_content)
                            final_content += final_event_content
                        analysis_completed = True
                        break
                    elif event_type == "error":
                        # Handle error events
                        error_content = event.get("content", "Analysis encountered an error")
                        result_parts.append(f"|_ Error: {error_content}\n")
                        error_occurred = True
                        break

                # Add appropriate completion message
                if error_occurred:
                    result_parts.append(f"\n|_ Analysis failed with error ({tool_use_count} tools used)\n")
                elif not analysis_completed:
                    result_parts.append(f"\n|_ Analysis completed - max iterations reached ({tool_use_count} tools used)\n")
                else:
                    result_parts.append(f"\n|_ Analysis completed successfully ({tool_use_count} tools used)\n")

                # If we didn't get meaningful content, add a summary based on tool usage
                if not final_content.strip() and tool_use_count > 0:
                    summary_content = f"|_ Note: Analysis executed {tool_use_count} tool operations but returned no text output\n"
                    result_parts.append(summary_content)

                # Combine results
                final_result = "".join(result_parts).strip()

                # Ensure we have meaningful output
                if not final_result or len(final_result) < 50:  # Very short output
                    base_info = f"🏗️ **Architect Analysis**\n\n|_ Analysis request: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\n"
                    if tool_use_count > 0:
                        base_info += f"|_ Executed {tool_use_count} tool operations\n"
                        base_info += "|_ Analysis completed successfully\n"
                    else:
                        base_info += "|_ Analysis completed but no tools were used\n"

                    if final_content.strip():
                        base_info += f"\n**Analysis Result:**\n{final_content.strip()}\n"

                    final_result = base_info

                # Add execution summary
                duration = time.time() - start_time
                summary = f"\n\n---\n**Summary:** {tool_use_count} tool uses, {duration:.1f}s"
                
                return ToolResult(
                    call_id="architect_tool",
                    result=final_result + summary,
                    metadata={
                        "tool_use_count": tool_use_count,
                        "duration": duration,
                        "agent_type": "architect"
                    }
                )
                
            except Exception as e:
                logger.error(f"Architect execution failed: {e}")
                return ToolResult(
                    call_id="architect_tool",
                    error=f"Architect execution failed: {str(e)}",
                    metadata={"error": "architect_execution_failed"}
                )
                
        except Exception as e:
            logger.error(f"Architect tool execution failed: {e}")
            return ToolResult(
                call_id="architect_tool",
                error=f"Architect tool failed: {str(e)}",
                metadata={"error": "architect_tool_failed"}
            )
    
    async def _create_architect_agent(self, parent_agent):
        """Create an architect sub-agent with read-only tools"""
        # Import here to avoid circular imports
        from pywen.agents.claude.claude_agent import ClaudeAgent
        
        # Create architect sub-agent instance
        architect_agent = ClaudeAgent(parent_agent.config, parent_agent.cli_console)
        
        # Set read-only tools only
        allowed_tools = self._get_architect_tools(parent_agent.tools)
        architect_agent.tools = allowed_tools
        
        # Copy context
        architect_agent.project_path = parent_agent.project_path
        architect_agent.context = parent_agent.context.copy()
        
        return architect_agent
    
    def _get_architect_tools(self, parent_tools: List[BaseTool]) -> List[BaseTool]:
        allowed_tool_names = {
            'read_file', 'read_many_files', 'ls', 'grep', 'glob',
            'web_fetch', 'web_search' 
        }
        return [tool for tool in parent_tools if tool.name in allowed_tool_names]
    
    def _get_architect_system_prompt(self) -> str:
        """Get system prompt for architect"""
        return ARCHITECT_SYSTEM_PROMPT 

    def build(self, provider:str = "", func_type : str = "") -> Mapping[str, Any]:
        """ claude 专用 """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameter_schema,
        }
