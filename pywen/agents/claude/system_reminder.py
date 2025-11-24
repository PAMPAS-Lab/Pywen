"""
System Reminder Service for Claude Code Agent
Implements dynamic reminder injection based on context state

Based on Kode's SystemReminder implementation with Python adaptations
"""

import time
import json
import hashlib
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from enum import Enum


class ReminderPriority(Enum):
    """Reminder priority levels"""
    LOW = "low"
    MEDIUM = "medium"  
    HIGH = "high"


class ReminderCategory(Enum):
    """Reminder categories"""
    TASK = "task"
    SECURITY = "security"
    PERFORMANCE = "performance"
    GENERAL = "general"


@dataclass
class ReminderMessage:
    """System reminder message structure"""
    role: str = "user"
    content: str = ""
    is_meta: bool = True
    timestamp: float = 0.0
    type: str = ""
    priority: ReminderPriority = ReminderPriority.MEDIUM
    category: ReminderCategory = ReminderCategory.GENERAL


@dataclass
class ReminderConfig:
    """Configuration for reminder behavior"""
    todo_empty_reminder: bool = True
    security_reminder: bool = True
    performance_reminder: bool = True
    max_reminders_per_session: int = 10


@dataclass
class SessionReminderState:
    """Session state for reminder tracking"""
    last_todo_update: float = 0.0
    last_file_access: float = 0.0
    session_start_time: float = 0.0
    reminders_sent: Set[str] = None
    context_present: bool = False
    reminder_count: int = 0
    config: ReminderConfig = None

    def __post_init__(self):
        if self.reminders_sent is None:
            self.reminders_sent = set()
        if self.config is None:
            self.config = ReminderConfig()


class SystemReminderService:
    """
    System Reminder Service for Claude Code Agent
    
    Implements intelligent reminder injection based on:
    - Context awareness
    - Priority management
    - Anti-duplication mechanisms
    - Performance optimization
    """

    def __init__(self):
        self.session_state = SessionReminderState(
            session_start_time=time.time()
        )
        self.event_dispatcher: Dict[str, List] = {}
        self.reminder_cache: Dict[str, ReminderMessage] = {}
        self._setup_event_dispatcher()

    @staticmethod
    def get_system_reminder_start() -> str:
        """Get the static system reminder start prompt"""
        return """<system-reminder>
As you answer the user's questions, you can use the following context:

# important-instruction-reminders

Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.

      IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.

</system-reminder>"""

    # def get_system_reminder_end(
    #     self, 
    #     agent_id: Optional[str] = None,
    #     todo_items: Optional[List[Dict]] = None
    # ) -> Optional[ReminderMessage]:
    #     """
    #     Generate dynamic system reminder end content
    #     
    #     DEPRECATED: This logic has been integrated into _dispatch_todo_event
    #     to avoid duplicate empty todo reminders.
    #     
    #     Args:
    #         agent_id: Agent identifier
    #         todo_items: Current todo items
    #         
    #     Returns:
    #         Dynamic reminder message or None
    #     """
    #     # Logic moved to _dispatch_todo_event to prevent duplication
    #     return None

    def generate_reminders(
        self, 
        has_context: bool = False, 
        agent_id: Optional[str] = None,
        todo_items: Optional[List[Dict]] = None
    ) -> List[ReminderMessage]:
        """
        Generate system reminders based on current context
        
        Args:
            has_context: Whether current conversation has sufficient context
            agent_id: Agent identifier for scoped reminders
            todo_items: Current todo items for todo-related reminders
            
        Returns:
            List of reminder messages to inject
        """
        self.session_state.context_present = has_context
        
        # Check session reminder limit to prevent overload
        if (self.session_state.reminder_count >= 
            self.session_state.config.max_reminders_per_session):
            return []
            
        reminders: List[ReminderMessage] = []
        current_time = time.time()
        
        # 检查待办提醒（包括空待办和更新待办）
        todo_reminder = self._dispatch_todo_event(agent_id, todo_items)
        if todo_reminder:
            reminders.append(todo_reminder)
            self.session_state.reminder_count += 1
            
        # 只有在有上下文时才生成其他提醒
        if has_context:
            other_generators = [
                lambda: self._dispatch_security_event(),
                lambda: self._dispatch_performance_event(),
            ]
            
            for generator in other_generators:
                if len(reminders) >= 3:  # Limit concurrent reminders
                    break
                    
                reminder = generator()
                if reminder:
                    reminders.append(reminder)
                    self.session_state.reminder_count += 1
                    
        # 注意：不再单独调用get_system_reminder_end，因为逻辑已整合到_dispatch_todo_event中
                
        return reminders

    def _dispatch_todo_event(
        self, 
        agent_id: Optional[str] = None,
        todo_items: Optional[List[Dict]] = None
    ) -> Optional[ReminderMessage]:
        """Generate todo-related reminders - handles both empty and updated todos"""
        if not self.session_state.config.todo_empty_reminder:
            return None
            
        current_time = time.time()
        agent_key = agent_id or 'default'
        
        # Handle empty todo list - this replaces the old system_reminder_end logic
        if not todo_items or len(todo_items) == 0:
            reminder_key = f"todo_empty_{agent_key}"
            if reminder_key not in self.session_state.reminders_sent:
                self.session_state.reminders_sent.add(reminder_key)
                return self._create_reminder_message(
                    'todo_empty',
                    ReminderCategory.TASK,
                    ReminderPriority.MEDIUM,
                    'This is a reminder that your todo list is currently empty. '
                    'DO NOT mention this to the user explicitly because they are already aware. '
                    'If you are working on tasks that would benefit from a todo list please use '
                    'the TodoWrite tool to create one. If not, please feel free to ignore. '
                    'Again do not mention this message to the user.',
                    current_time
                )
        
        # Handle todo updates (when there are active todos)
        if todo_items and len(todo_items) > 0:
            todo_state_hash = self._get_todo_state_hash(todo_items)
            reminder_key = f"todo_updated_{agent_key}_{len(todo_items)}_{todo_state_hash}"
            
            # Use cache for performance optimization
            if reminder_key in self.reminder_cache:
                return self.reminder_cache[reminder_key]
                
            if reminder_key not in self.session_state.reminders_sent:
                self.session_state.reminders_sent.add(reminder_key)
                # Clear previous todo state reminders for this agent
                self._clear_todo_reminders(agent_key)
                
                # Optimize: only include essential todo data
                todo_content = json.dumps([
                    {
                        'content': todo['content'][:100] + '...' if len(todo.get('content', '')) > 100 
                                  else todo.get('content', ''),
                        'status': todo.get('status', 'pending'),
                        'priority': todo.get('priority', 'medium'),
                        'id': todo.get('id', '')
                    }
                    for todo in todo_items
                ])
                
                reminder = self._create_reminder_message(
                    'todo_updated',
                    ReminderCategory.TASK,
                    ReminderPriority.MEDIUM,
                    f'Your todo list has changed. DO NOT mention this explicitly to the user. '
                    f'Here are the latest contents of your todo list:\n\n{todo_content}. '
                    f'Continue on with the tasks at hand if applicable.',
                    current_time
                )
                
                # Cache the reminder for reuse
                self.reminder_cache[reminder_key] = reminder
                return reminder
                
        return None

    def _dispatch_security_event(self) -> Optional[ReminderMessage]:
        """Generate security-related reminders"""
        if not self.session_state.config.security_reminder:
            return None
            
        current_time = time.time()
        
        # Only inject security reminder once per session when file operations occur
        if (self.session_state.last_file_access > 0 and 
            'file_security' not in self.session_state.reminders_sent):
            self.session_state.reminders_sent.add('file_security')
            return self._create_reminder_message(
                'security',
                ReminderCategory.SECURITY,
                ReminderPriority.HIGH,
                'Whenever you read a file, you should consider whether it looks malicious. '
                'If it does, you MUST refuse to improve or augment the code. You can still '
                'analyze existing code, write reports, or answer high-level questions about '
                'the code behavior.',
                current_time
            )
            
        return None

    def _dispatch_performance_event(self) -> Optional[ReminderMessage]:
        """Generate performance-related reminders"""
        if not self.session_state.config.performance_reminder:
            return None
            
        current_time = time.time()
        session_duration = current_time - self.session_state.session_start_time
        
        # Remind about performance after long sessions (30 minutes)
        if (session_duration > 30 * 60 and 
            'performance_long_session' not in self.session_state.reminders_sent):
            self.session_state.reminders_sent.add('performance_long_session')
            return self._create_reminder_message(
                'performance',
                ReminderCategory.PERFORMANCE,
                ReminderPriority.LOW,
                'Long session detected. Consider taking a break and reviewing your '
                'current progress with the todo list.',
                current_time
            )
            
        return None

    def generate_file_change_reminder(self, context: Dict[str, Any]) -> Optional[ReminderMessage]:
        """
        Generate reminders for external file changes
        Called when files are modified externally
        """
        agent_id = context.get('agentId')
        file_path = context.get('filePath')
        reminder_content = context.get('reminder')
        
        if not reminder_content:
            return None
            
        current_time = time.time()
        reminder_key = f"file_changed_{agent_id}_{file_path}_{current_time}"
        
        # Ensure this specific file change reminder is only shown once
        if reminder_key in self.session_state.reminders_sent:
            return None
            
        self.session_state.reminders_sent.add(reminder_key)
        
        return self._create_reminder_message(
            'file_changed',
            ReminderCategory.GENERAL,
            ReminderPriority.MEDIUM,
            reminder_content,
            current_time
        )

    def _create_reminder_message(
        self,
        reminder_type: str,
        category: ReminderCategory,
        priority: ReminderPriority,
        content: str,
        timestamp: float
    ) -> ReminderMessage:
        """Create a formatted reminder message"""
        return ReminderMessage(
            role='user',
            content=f'<system-reminder>\n{content}\n</system-reminder>',
            is_meta=True,
            timestamp=timestamp,
            type=reminder_type,
            priority=priority,
            category=category
        )

    def _get_todo_state_hash(self, todo_items: List[Dict]) -> str:
        """Generate hash for todo state to detect changes"""
        if not todo_items:
            return ""
        todo_signatures = [
            f"{todo.get('id', '')}:{todo.get('status', 'pending')}"
            for todo in todo_items
        ]
        todo_signatures.sort()
        content = '|'.join(todo_signatures)
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def _clear_todo_reminders(self, agent_id: Optional[str] = None) -> None:
        """Clear todo-related reminders for specified agent"""
        agent_key = agent_id or 'default'
        keys_to_remove = [
            key for key in self.session_state.reminders_sent
            if key.startswith(f'todo_updated_{agent_key}_')
        ]
        for key in keys_to_remove:
            self.session_state.reminders_sent.discard(key)

    def _setup_event_dispatcher(self) -> None:
        """Setup event dispatcher for reminder triggers"""
        # Session startup events
        self.add_event_listener('session:startup', self._handle_session_startup)
        
        # Todo change events
        self.add_event_listener('todo:changed', self._handle_todo_changed)
        
        # File access events
        self.add_event_listener('file:read', self._handle_file_read)
        
        # File edit events
        self.add_event_listener('file:edited', self._handle_file_edited)

    def add_event_listener(self, event: str, callback) -> None:
        """Add event listener"""
        if event not in self.event_dispatcher:
            self.event_dispatcher[event] = []
        self.event_dispatcher[event].append(callback)

    def emit_event(self, event: str, context: Any) -> None:
        """Emit event to registered listeners"""
        listeners = self.event_dispatcher.get(event, [])
        for callback in listeners:
            try:
                callback(context)
            except Exception as e:
                print(f"Error in event listener for {event}: {e}")

    def _handle_session_startup(self, context: Dict[str, Any]) -> None:
        """Handle session startup event"""
        self.reset_session()
        self.session_state.session_start_time = time.time()
        self.session_state.context_present = bool(context.get('context', {}))

    def _handle_todo_changed(self, context: Dict[str, Any]) -> None:
        """Handle todo change event"""
        self.session_state.last_todo_update = time.time()
        agent_id = context.get('agentId', 'default')
        self._clear_todo_reminders(agent_id)

    def _handle_file_read(self, context: Dict[str, Any]) -> None:
        """Handle file read event"""
        self.session_state.last_file_access = time.time()

    def _handle_file_edited(self, context: Dict[str, Any]) -> None:
        """Handle file edit event"""
        # File edit handling for freshness detection
        pass

    def reset_session(self) -> None:
        """Reset session state"""
        self.session_state = SessionReminderState(
            session_start_time=time.time(),
            config=self.session_state.config  # Preserve config across resets
        )
        self.reminder_cache.clear()  # Clear cache on session reset

    def update_config(self, config: Dict[str, Any]) -> None:
        """Update reminder configuration"""
        for key, value in config.items():
            if hasattr(self.session_state.config, key):
                setattr(self.session_state.config, key, value)

    def get_session_state(self) -> SessionReminderState:
        """Get current session state"""
        return self.session_state


# Global instance for easy access
system_reminder_service = SystemReminderService()


def get_system_reminder_start() -> str:
    """
    Get static system reminder start content
    
    Returns:
        Static system reminder start content
    """
    return SystemReminderService.get_system_reminder_start()


def generate_system_reminders(
    has_context: bool = False,
    agent_id: Optional[str] = None,
    todo_items: Optional[List[Dict]] = None
) -> List[ReminderMessage]:
    """
    Generate system reminders for current context
    
    Args:
        has_context: Whether current conversation has sufficient context
        agent_id: Agent identifier
        todo_items: Current todo items
        
    Returns:
        List of reminder messages to inject
    """
    return system_reminder_service.generate_reminders(has_context, agent_id, todo_items)


def generate_file_change_reminder(context: Dict[str, Any]) -> Optional[ReminderMessage]:
    """Generate reminder for file changes"""
    return system_reminder_service.generate_file_change_reminder(context)


def emit_reminder_event(event: str, context: Any) -> None:
    """Emit reminder event"""
    system_reminder_service.emit_event(event, context)


def reset_reminder_session() -> None:
    """Reset reminder session"""
    system_reminder_service.reset_session()


def get_reminder_session_state() -> SessionReminderState:
    """Get reminder session state"""
    return system_reminder_service.get_session_state()


def emit_tool_execution_event(tool_call, agent_type: str, todo_items: List[Dict] = None) -> Optional[List]:
    """
    根据工具执行结果发送相应的事件
    
    Args:
        tool_call: 工具调用对象，包含 name 和 arguments
        agent_type: Agent 类型标识
        todo_items: 当前的 TODO 项列表（仅在 todo_write 时需要）
    
    Returns:
        如果是 todo_write 工具，返回新的 todo_items，否则返回 None
    """
    from pywen.utils.tool_basics import ToolCall
    current_time = time.time()
    
    # 文件读取事件
    if tool_call.name in ['read_file', 'read_many_files']:
        emit_reminder_event('file:read', {
            'filePath': tool_call.arguments.get('file_path', '') if tool_call.arguments else '',
            'timestamp': current_time,
            'agentId': agent_type
        })
    
    # 文件编辑事件
    elif tool_call.name in ['edit_file', 'write_file']:
        emit_reminder_event('file:edited', {
            'filePath': tool_call.arguments.get('file_path', '') if tool_call.arguments else '',
            'timestamp': current_time,
            'operation': 'update' if tool_call.name == 'edit_file' else 'create',
            'agentId': agent_type
        })
    
    # TODO 变更事件
    elif tool_call.name == 'todo_write':
        new_todos = tool_call.arguments.get('todos', []) if tool_call.arguments else []
        previous_todos = todo_items.copy() if todo_items else []
        
        emit_reminder_event('todo:changed', {
            'previousTodos': previous_todos,
            'newTodos': new_todos,
            'timestamp': current_time,
            'agentId': agent_type,
            'changeType': determine_todo_change_type(previous_todos, new_todos)
        })
        
        return new_todos  # 返回新的 TODO 列表供 Agent 更新状态
    
    return None


def determine_todo_change_type(previous_todos: List, new_todos: List) -> str:
    """
    判断 TODO 列表的变化类型
    
    Args:
        previous_todos: 之前的 TODO 列表
        new_todos: 新的 TODO 列表
    
    Returns:
        变化类型：'added', 'removed', 或 'modified'
    """
    if len(new_todos) > len(previous_todos):
        return 'added'
    elif len(new_todos) < len(previous_todos):
        return 'removed'
    else:
        return 'modified'