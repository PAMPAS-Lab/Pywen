import logging
import time
import uuid
from typing import List, Mapping, Any
from pywen.tools.base_tool import BaseTool
from pywen.utils.tool_basics import ToolResult
from pywen.utils.llm_basics import LLMMessage
from pywen.core.tool_registry2 import register_tool

logger = logging.getLogger(__name__)

CLAUDE_DESCRIPTION = """
Launch a new agent to handle complex, multi-step tasks autonomously.

Available agent types and the tools they have access to:
- general-purpose: General-purpose agent for researching complex questions, searching for code, and executing multi-step tasks. When you are searching for a keyword or file and are not confident that you will find the right match in the first few tries use this agent to perform the search for you. (Tools: *)

When using the Task tool, you must specify a subagent_type parameter to select which agent type to use.

When to use the Task tool:
- When you are instructed to execute custom slash commands. Use the Task tool with the slash command invocation as the entire prompt. The slash command can take arguments. For example: Task(description="Check the file", prompt="/check-file path/to/file.py")

When NOT to use the Task tool:
- If you want to read a specific file path, use the Read or Glob tool instead of the Task tool, to find the match more quickly
- If you are searching for a specific class definition like "class Foo", use the Glob tool instead, to find the match more quickly
- If you are searching for code within a specific file or set of 2-3 files, use the Read tool instead of the Task tool, to find the match more quickly
- Other tasks that are not related to the agent descriptions above

Usage notes:
1. Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses
2. When the agent is done, it will return a single message back to you. The result returned by the agent is not visible to the user. To show the user the result, you should send a text message back to the user with a concise summary of the result.
3. Each agent invocation is stateless. You will not be able to send additional messages to the agent, nor will the agent be able to communicate with you outside of its final report. Therefore, your prompt should contain a highly detailed task description for the agent to perform autonomously and you should specify exactly what information the agent should return back to you in its final and only message to you.
4. The agent's outputs should generally be trusted
5. Clearly tell the agent whether you expect it to write code or just to do research (search, file reads, web fetches, etc.), since it is not aware of the user's intent
6. If the agent description mentions that it should be used proactively, then you should try your best to use it without the user having to ask for it first. Use your judgement.
"""

SYSTEM_PROMPT_TEMPLATE = """
You are a focused task agent for Claude Code. Your role is to complete the specific task: "{description}".

## Task Management Guidelines
- Break down complex tasks into smaller, manageable steps
- Use the TodoWrite tool to maintain a todo list for tracking progress
- Update todo items as you complete each step
- Be systematic and thorough in your approach
- Complete the task autonomously and return comprehensive results

## Todo List Management
- Create todo items for each major step of the task
- Use status: 'pending' for new tasks, 'in_progress' for current work, 'completed' for finished items
- Set appropriate priority: 'high', 'medium', or 'low'
- Update the todo list as you progress through the task

## Thinking and Reasoning
- Use the Think tool to log your reasoning process when analyzing complex problems
- Think through multiple approaches before implementing solutions
- Document your decision-making process for transparency
- Use thinking especially when debugging or planning complex changes

## Tool Usage
- Use tools efficiently and in parallel when possible
- Focus on read-only operations when possible for analysis tasks
- Be precise with file operations and command execution
- Use absolute file paths when referencing files

## Task Completion
- Provide clear, actionable results that directly address the task
- Include a summary of what was accomplished
- Ensure all todo items are properly updated to reflect completion status

## Important Notes
- This is a task agent execution (ID: {task_id}) - be direct and task-focused
- Your response will be returned to the parent agent
- Maintain the todo list throughout the task execution
- Complete the task systematically and thoroughly
"""

@register_tool(name="task_tool", providers=["claude",])
class TaskTool(BaseTool):
    name="task_tool"
    display_name="Task Agent"
    description=CLAUDE_DESCRIPTION
    parameter_schema={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "A short (3-5 word) description of the task"
            },
            "prompt": {
                "type": "string",
                "description": "The detailed task for the agent to perform. Be specific about what information you need back."
            }
        },
        "required": ["description", "prompt"]
    }
    
    def set_current_agent(self, agent):
        self.current_agent = agent
    
    def is_risky(self, **kwargs) -> bool:
        """Task tool is generally safe as it uses restricted tools"""
        return False
    
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the task tool by launching a sub-agent with todo list management
        """
        description = kwargs.get('description', '')
        prompt = kwargs.get('prompt', '')
        
        try:
            start_time = time.time()
            if not self.current_agent or self.current_agent.type != "ClaudeAgent":
                return ToolResult(
                    call_id="task_tool",
                    error="Task tool can only be used with Claude Code Agent",
                    metadata={"error": "invalid_agent_type"}
                )
            task_id = str(uuid.uuid4())[:8]
            sub_agent = await self._create_sub_agent(self.current_agent, task_id)
            result_parts = [f"🎯 **Task Execution** `{task_id}`\n\n"]
            result_parts.append(f"|_ Task: {description}\n")
            result_parts.append("|_ Initializing sub-agent...\n")
            tool_use_count = 0

            try:
                system_prompt = self._get_task_system_prompt(description, task_id)
                result_parts.append("|_ Starting task execution...\n\n")

                final_content = ""
                task_completed = False
                error_occurred = False

                async for event in sub_agent._query_recursive(
                    messages=[
                        LLMMessage(role="system", content=system_prompt),
                        LLMMessage(role="user", content=prompt)
                    ],
                    system_prompt=system_prompt,
                    max_iterations=10
                ):
                    event_type = event.get("type", "")

                    if event_type == "content":
                        content = event.get("content", "")
                        if content.strip():
                            result_parts.append(content)
                            final_content += content
                    elif event_type == "tool_call_start":
                        tool_data = event.get("data", {})
                        tool_name = tool_data.get("name", "unknown")
                        tool_args = tool_data.get("arguments", {})
                        
                        if tool_name == "read_file" and "file_path" in tool_args:
                            result_parts.append(f"|_ 📖 Reading file: {tool_args['file_path']}\n")
                        elif tool_name == "write_file" and "file_path" in tool_args:
                            result_parts.append(f"|_ ✏️ Writing file: {tool_args['file_path']}\n")
                        elif tool_name == "edit_file" and "file_path" in tool_args:
                            result_parts.append(f"|_ ✏️ Editing file: {tool_args['file_path']}\n")
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
                        elif tool_name == "todo_write":
                            result_parts.append(f"|_ ✅ Updating todo list\n")
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
                        if event.get("content"):
                            final_event_content = event["content"]
                            result_parts.append(final_event_content)
                            final_content += final_event_content
                        task_completed = True
                        break
                    elif event_type == "error":
                        error_content = event.get("content", "Task encountered an error")
                        result_parts.append(f"|_ Error: {error_content}\n")
                        error_occurred = True
                        break

                if error_occurred:
                    result_parts.append(f"\n|_ Task `{task_id}` failed with error ({tool_use_count} tools used)\n")
                elif not task_completed:
                    result_parts.append(f"\n|_ Task `{task_id}` completed - max iterations reached ({tool_use_count} tools used)\n")
                else:
                    result_parts.append(f"\n|_ Task `{task_id}` completed successfully ({tool_use_count} tools used)\n")

                if not final_content.strip() and tool_use_count > 0:
                    summary_content = f"|_ Note: Task executed {tool_use_count} tool operations but returned no text output\n"
                    result_parts.append(summary_content)

                final_result = "".join(result_parts).strip()

                if not final_result or len(final_result) < 50:
                    base_info = f"🎯 **Task Execution** `{task_id}`\n\n|_ Task: {description}\n"
                    if tool_use_count > 0:
                        base_info += f"|_ Executed {tool_use_count} tool operations\n"
                        base_info += "|_ Task completed successfully\n"
                    else:
                        base_info += "|_ Task completed but no tools were used\n"

                    if final_content.strip():
                        base_info += f"\n**Output:**\n{final_content.strip()}\n"

                    final_result = base_info

                duration = time.time() - start_time
                summary = f"\n\n---\n**Summary:** Task `{task_id}` - {tool_use_count} tool uses, {duration:.1f}s"
                
                return ToolResult(
                    call_id="task_tool",
                    result=final_result + summary,
                    metadata={
                        "task_id": task_id,
                        "description": description,
                        "tool_use_count": tool_use_count,
                        "duration": duration,
                        "agent_type": "task_agent"
                    }
                )
                
            except Exception as e:
                logger.error(f"Task execution failed: {e}")
                return ToolResult(
                    call_id="task_tool",
                    error=f"Task execution failed: {str(e)}",
                    metadata={"error": "task_execution_failed", "task_id": task_id}
                )
                
        except Exception as e:
            logger.error(f"Task tool execution failed: {e}")
            return ToolResult(
                call_id="task_tool",
                error=f"Task tool failed: {str(e)}",
                metadata={"error": "task_tool_failed"}
            )
    
    async def _create_sub_agent(self, parent_agent, task_id: str):
        """Create a sub-agent with restricted tools including todo management"""
        from pywen.agents.claude.claude_agent import ClaudeAgent
        sub_agent = ClaudeAgent(parent_agent.config, parent_agent.cli_console)
        
        allowed_tools = self._get_task_tools(parent_agent.tools, task_id)
        sub_agent.tools = allowed_tools
        
        sub_agent.project_path = parent_agent.project_path
        sub_agent.context = parent_agent.context.copy()
        
        sub_agent.task_id = task_id
        
        return sub_agent
    
    def _get_task_tools(self, parent_tools: List[BaseTool], task_id: str) -> List[BaseTool]:
        """Get allowed tools for task agent including todo management"""
        allowed_tool_names = {
            'read_file', 'read_many_files', 'write_file', 'edit_file',
            'ls', 'grep', 'glob', 'bash', 'web_fetch', 'web_search',
            'memory_read', 'memory_write', 'todo_write', 'think'
        }
        
        filtered_tools = [
            tool for tool in parent_tools
            if (tool.name in allowed_tool_names and 
                tool.name not in ['agent_tool', 'task_tool', 'architect_tool'])
        ]
        
        if not any(tool.name == 'todo_write' for tool in filtered_tools):
            from .todo_tool import TodoTool
            todo_tool = TodoTool(task_id=task_id)
            filtered_tools.append(todo_tool)
        
        return filtered_tools
    
    def _get_task_system_prompt(self, description: str, task_id: str) -> str:
        """Get system prompt for task agent with todo list management"""
        return SYSTEM_PROMPT_TEMPLATE.format(
            description=description,
            task_id=task_id
        )

    def build(self, provider:str = "", func_type: str = "") -> Mapping[str, Any]:
        """ claude 专用 """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameter_schema,
        }
