"""
Todo Tool - Manage todo lists for task tracking
Based on Kode's TodoWriteTool implementation
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


from pywen.tools.base import BaseTool
from pywen.utils.tool_basics import ToolResult

logger = logging.getLogger(__name__)

# Global todo tool instances for agent sessions
_todo_tool_instances = {}


def get_todo_tool(agent_id: str = "default") -> 'TodoTool':
    """Get or create a TodoTool instance for the given agent"""
    if agent_id not in _todo_tool_instances:
        _todo_tool_instances[agent_id] = TodoTool(agent_id)
    return _todo_tool_instances[agent_id]


def get_current_todos(agent_id: str = "default") -> List['TodoItem']:
    """Get current todos for an agent"""
    tool = get_todo_tool(agent_id)
    return tool.storage.get_todos()


def update_todos(todos: List[Dict[str, Any]], agent_id: str = "default") -> str:
    """Update todos for an agent and return formatted display"""
    tool = get_todo_tool(agent_id)

    # Convert to TodoItem objects
    todo_items = []
    for todo_data in todos:
        todo_item = TodoItem(
            id=todo_data["id"],
            content=todo_data["content"],
            status=todo_data["status"]
        )
        todo_items.append(todo_item)

    # Save todos
    tool.storage.set_todos(todo_items)

    # Return formatted display
    return tool._format_todos_for_display(todo_items)


class TodoItem:
    """Todo item data structure"""
    def __init__(self, id: str, content: str, status: str = "pending", 
                 created_at: Optional[int] = None,
                 updated_at: Optional[int] = None):
        self.id = id
        self.content = content
        self.status = status  # pending, in_progress, completed
        self.created_at = created_at or self._current_timestamp()
        self.updated_at = updated_at or self._current_timestamp()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TodoItem':
        return cls(
            id=data["id"],
            content=data["content"],
            status=data.get("status", "pending"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at")
        )
    
    def _current_timestamp(self) -> int:
        import time
        return int(time.time() * 1000)


class TodoStorage:
    """Todo storage manager with caching and auto-update"""

    def __init__(self, agent_id: str = "default"):
        self.agent_id = agent_id
        self._storage_dir = self._get_storage_dir()
        self._storage_file = self._storage_dir / f"todos_{agent_id}.json"
        self._cache = None
        self._cache_timestamp = 0
        self._cache_ttl = 5000  # 5 seconds cache TTL

    def _get_storage_dir(self) -> Path:
        """Get the storage directory for todos"""
        from pywen.config.loader import get_pywen_config_dir
        todos_dir = get_pywen_config_dir() / "todos"
        todos_dir.mkdir(exist_ok=True)
        return todos_dir

    def _invalidate_cache(self):
        """Invalidate the cache"""
        self._cache = None
        self._cache_timestamp = 0
    
    def get_todos(self) -> List['TodoItem']:
        """Get all todos for this agent with caching"""
        current_time = int(time.time() * 1000)

        # Check cache first
        if (self._cache is not None and
            current_time - self._cache_timestamp < self._cache_ttl):
            return self._cache.copy()

        # Load from file
        if not self._storage_file.exists():
            self._cache = []
            self._cache_timestamp = current_time
            return []

        try:
            with open(self._storage_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                todos = [TodoItem.from_dict(item) for item in data]

                # Update cache
                self._cache = todos.copy()
                self._cache_timestamp = current_time

                return todos
        except Exception as e:
            logger.error(f"Error loading todos: {e}")
            self._cache = []
            self._cache_timestamp = current_time
            return []
    
    def set_todos(self, todos: List['TodoItem']) -> None:
        """Set todos for this agent with smart sorting and caching"""
        try:
            existing_todos = self.get_todos()
            current_time = int(time.time() * 1000)

            # Process todos with timestamps and status tracking
            processed_todos = []
            for todo in todos:
                # Find existing todo to track status changes
                existing = next((t for t in existing_todos if t.id == todo.id), None)

                # Update timestamps
                if existing:
                    # Keep original creation time, update modified time
                    todo.created_at = existing.created_at
                    todo.updated_at = current_time
                else:
                    # New todo
                    todo.created_at = current_time
                    todo.updated_at = current_time

                processed_todos.append(todo)

            # Smart sorting: status > updated_at (sequential execution order)
            processed_todos.sort(key=lambda t: (
                {'in_progress': 3, 'pending': 2, 'completed': 1}[t.status],
                -t.updated_at
            ), reverse=True)

            # Save to file
            data = [todo.to_dict() for todo in processed_todos]
            with open(self._storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Update cache
            self._cache = processed_todos.copy()
            self._cache_timestamp = current_time

        except Exception as e:
            logger.error(f"Error saving todos: {e}")
            self._invalidate_cache()
            raise


class TodoTool(BaseTool):
    """
    Todo Tool for managing task todo lists
    """
    
    def __init__(self, agent_id: str = None, config=None):
        # Handle case where config is passed as first argument (from tool registry)
        if agent_id is not None and not isinstance(agent_id, str):
            config = agent_id
            agent_id = None

        # Generate a proper agent_id
        if agent_id is None:
            import uuid
            agent_id = f"claude_code_{str(uuid.uuid4())[:8]}"

        super().__init__(
            name="todo_write",
            display_name="Todo Manager",
            description="""Use this tool to create and manage a structured task list for your current coding session. This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.
It also helps the user understand the progress of the task and overall progress of their requests.

## When to Use This Tool
Use this tool proactively in these scenarios:

1. Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
2. Non-trivial and complex tasks - Tasks that require careful planning or multiple operations
3. User explicitly requests todo list - When the user directly asks you to use the todo list
4. User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
5. After receiving new instructions - Immediately capture user requirements as todos
6. When you start working on a task - Mark it as in_progress BEFORE beginning work. Ideally you should only have one todo as in_progress at a time
7. After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation

## When NOT to Use This Tool

Skip using this tool when:
1. There is only a single, straightforward task
2. The task is trivial and tracking it provides no organizational benefit
3. The task can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

NOTE that you should not use this tool if there is only one trivial task to do. In this case you are better off just doing the task directly.

## Task States and Management

1. **Task States**: Use these states to track progress:
   - pending: Task not yet started
   - in_progress: Currently working on (limit to ONE task at a time)
   - completed: Task finished successfully

2. **Task Management**:
   - Update task status in real-time as you work
   - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
   - Only have ONE task in_progress at any time
   - Complete current tasks before starting new ones
   - Remove tasks that are no longer relevant from the list entirely

3. **Task Completion Requirements**:
   - ONLY mark a task as completed when you have FULLY accomplished it
   - If you encounter errors, blockers, or cannot finish, keep the task as in_progress
   - When blocked, create a new task describing what needs to be resolved
   - Never mark a task as completed if:
     - Tests are failing
     - Implementation is partial
     - You encountered unresolved errors
     - You couldn't find necessary files or dependencies

4. **Task Breakdown**:
   - Create specific, actionable items
   - Break complex tasks into smaller, manageable steps
   - Use clear, descriptive task names

When in doubt, use this tool. Being proactive with task management demonstrates attentiveness and ensures you complete all requirements successfully.""",
            parameter_schema={
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "The updated todo list",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Unique identifier for the task"
                                },
                                "content": {
                                    "type": "string",
                                    "description": "The task description or content"
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "Current status of the task"
                                }
                            },
                            "required": ["id", "content", "status"]
                        }
                    }
                },
                "required": ["todos"]
            },
            is_output_markdown=False,
            can_update_output=False,
            config=config
        )
        self.agent_id = agent_id
        self.storage = TodoStorage(agent_id)
    
    def is_risky(self, **kwargs) -> bool:
        """Todo tool is safe"""
        return False
    
    async def execute(self, todos: List[Dict[str, Any]], **kwargs) -> ToolResult:
        """
        Execute the todo tool to update the todo list
        """
        try:
            # Validate todos
            validation_result = self._validate_todos(todos)
            if not validation_result["valid"]:
                return ToolResult(
                    call_id="todo_write",
                    error=f"Todo validation failed: {validation_result['error']}",
                    metadata={"error": "validation_failed"}
                )
            
            # Get previous todos for comparison
            previous_todos = self.storage.get_todos()
            
            # Convert to TodoItem objects
            todo_items = []
            for todo_data in todos:
                # Find existing todo to preserve timestamps
                existing = next((t for t in previous_todos if t.id == todo_data["id"]), None)
                
                todo_item = TodoItem(
                    id=todo_data["id"],
                    content=todo_data["content"],
                    status=todo_data["status"],
                    created_at=existing.created_at if existing else None,
                    updated_at=None  # Will be set to current time
                )
                todo_items.append(todo_item)
            
            # Save todos
            self.storage.set_todos(todo_items)
            
            # Generate summary
            summary = self._generate_summary(todo_items)
            
            # Format todo list for display
            todo_display = self._format_todos_for_display(todo_items)
            
            return ToolResult(
                call_id="todo_write",
                result=f"{summary}\n\n{todo_display}",
                metadata={
                    "agent_id": self.agent_id,
                    "todo_count": len(todo_items),
                    "summary": summary
                }
            )
            
        except Exception as e:
            logger.error(f"Todo tool execution failed: {e}")
            return ToolResult(
                call_id="todo_write",
                error=f"Todo tool failed: {str(e)}",
                metadata={"error": "todo_tool_failed"}
            )
    
    def _validate_todos(self, todos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate todo list"""
        if not isinstance(todos, list):
            return {"valid": False, "error": "Todos must be a list"}
        
        # Check for duplicate IDs
        ids = [todo.get("id") for todo in todos]
        if len(ids) != len(set(ids)):
            return {"valid": False, "error": "Duplicate todo IDs found"}
        
        # Check for multiple in_progress tasks
        in_progress_count = sum(1 for todo in todos if todo.get("status") == "in_progress")
        if in_progress_count > 1:
            return {"valid": False, "error": "Only one task can be in_progress at a time"}
        
        # Validate each todo
        for todo in todos:
            if not todo.get("id"):
                return {"valid": False, "error": "Todo ID is required"}
            if not todo.get("content", "").strip():
                return {"valid": False, "error": f"Todo content is required for ID: {todo.get('id')}"}
            if todo.get("status") not in ["pending", "in_progress", "completed"]:
                return {"valid": False, "error": f"Invalid status for todo {todo.get('id')}: {todo.get('status')}"}
        
        return {"valid": True}
    
    def _generate_summary(self, todos: List[TodoItem]) -> str:
        """Generate summary of todo list"""
        total = len(todos)
        pending = sum(1 for t in todos if t.status == "pending")
        in_progress = sum(1 for t in todos if t.status == "in_progress")
        completed = sum(1 for t in todos if t.status == "completed")
        
        return f"Updated {total} todo(s) ({pending} pending, {in_progress} in progress, {completed} completed)"
    
    def _format_todos_for_display(self, todos: List[TodoItem]) -> str:
        """Format todos for display with proper Markdown checkbox formatting"""
        if not todos:
            return "No todos currently"

        lines = []

        for todo in todos:
            # Standard Markdown checkbox format
            if todo.status == "completed":
                checkbox = "- [x]"
                content_style = f"~~{todo.content}~~"
            elif todo.status == "in_progress":
                checkbox = "- [~]"  # Using ~ for in-progress
                content_style = f"**{todo.content}** *(in progress)*"
            else:  # pending
                checkbox = "- [ ]"
                content_style = todo.content

            # Format: - [x] content
            line = f"{checkbox} {content_style}"

            lines.append(line)

        # Add summary at the end
        total = len(todos)
        pending = sum(1 for t in todos if t.status == "pending")
        in_progress = sum(1 for t in todos if t.status == "in_progress")
        completed = sum(1 for t in todos if t.status == "completed")

        lines.append("")  # Empty line
        lines.append(f"**Progress:** {completed}/{total} completed • {in_progress} in progress • {pending} pending")

        return "\n".join(lines)
