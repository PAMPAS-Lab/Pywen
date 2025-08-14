"""CLI Console for displaying agent progress."""

from dataclasses import dataclass
from typing import Optional, Any, List

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pywen.config.config import Config, ApprovalMode
from pywen.ui.highlighted_content import create_enhanced_tool_result_display



class CLIConsole:
    """Console for displaying agent progress and handling user interactions."""

    def __init__(self, config: Optional[Config] = None):
        """Initialize the CLI console."""
        self.console: Console = Console()
        self.live_display: Live | None = None
        self.config: Config | None = config
        self.current_task: str = ""
        self.agent_execution: Any = None
        self.execution_log: List[Text] = []
        
        # Token tracking
        self.current_session_tokens = 0
        self.max_context_tokens = 32768  # Default, will be updated from config
        
        # Track displayed content to avoid duplicates
        self.displayed_iterations: set = set()
        self.displayed_responses: set = set()
        self.displayed_tool_calls: set = set()
        self.displayed_tool_results: set = set()

    def log_execution(self, message: Text):
        """Log execution message - keep logs but avoid duplicate display."""
        self.execution_log.append(message)
        # Keep only recent 20 records
        if len(self.execution_log) > 20:
            self.execution_log = self.execution_log[-20:]

    async def start(self):
        """Start the console monitoring - simplified version."""
        # No longer using loop updates, changed to event-driven
        pass

    def print(self, message: str, color: str = "blue", bold: bool = False):
        """Print a message with optional formatting."""
        text = Text(message, style=color)
        if bold:
            text.stylize("bold")
        self.console.print(text)
        # Also log to execution log
        self.log_execution(text)

    def print_llm_response(self, content: str):
        """Print LLM response - incremental display."""
        if content.strip():
            # Use content hash to avoid duplicate display
            content_hash = hash(content)
            if content_hash not in self.displayed_responses:
                self.displayed_responses.add(content_hash)
                text = Text("🤖 Assistant: ", style="blue")
                text.append(content)
                # Print content directly without Panel object
                self.console.print(text)
                self.log_execution(text)

    def print_tool_call(self, tool_name: str, arguments: dict):
        """Print tool call information - incremental display."""
        call_id = f"{tool_name}_{hash(str(arguments))}"
        if call_id not in self.displayed_tool_calls:
            self.displayed_tool_calls.add(call_id)
            
            # Special handling for bash tool to show specific command
            if tool_name == "bash" and "command" in arguments:
                command = arguments["command"]
                text = Text("🔧 Executing bash command: ", style="cyan")
                text.append(str(command))
            else:
                args_str = str(arguments)
                text = Text(f"🔧 Calling tool: {tool_name} with args: ", style="cyan")
                text.append(args_str)
            self.console.print(text)
            self.log_execution(text)

    def print_tool_result(self, tool_name: str, result: Any, success: bool = True):
        """Print tool result - incremental display."""
        result_id = f"{tool_name}_{hash(str(result))}"
        if result_id not in self.displayed_tool_results:
            self.displayed_tool_results.add(result_id)
            
            if success:
                result_str = str(result) if result else "Success"
                text = Text("✅ ", style="green")
                text.append(f"{tool_name} completed: ", style="bold green")
                text.append(result_str)
            else:
                error_str = str(result) if result else "Unknown error"
                text = Text("❌ ", style="red")
                text.append(f"{tool_name} failed: ", style="bold red")
                text.append(error_str)
            self.console.print(text)
            self.log_execution(text)

    def print_iteration_start(self, iteration: int):
        """Print iteration start - display only once."""
        if iteration not in self.displayed_iterations:
            self.displayed_iterations.add(iteration)
            text = Text(f"🔄 Starting iteration {iteration}", style="bold cyan")
            self.console.print(text)
            self.log_execution(Text(f"🔄 Iteration {iteration} started", style="cyan"))

    async def confirm_tool_call(self, tool_call, tool=None) -> bool:
        """Ask user to confirm tool execution."""
        # Use new permission system if available
        if hasattr(self, 'config') and hasattr(self.config, 'get_permission_manager'):
            permission_manager = self.config.get_permission_manager()
            tool_name = tool_call.name if hasattr(tool_call, 'name') else tool_call.get('name', 'unknown')
            arguments = tool_call.arguments if hasattr(tool_call, 'arguments') else tool_call.get('arguments', {})

            if permission_manager.should_auto_approve(tool_name, **arguments):
                return True

        # Fallback to old YOLO mode check for backward compatibility
        elif hasattr(self, 'config') and self.config.get_approval_mode() == ApprovalMode.YOLO:
            return True

        # Legacy tool risk level check
        if tool:
            from pywen.tools.base import ToolRiskLevel
            risk_level = tool.get_risk_level(**tool_call.arguments if hasattr(tool_call, 'arguments') else tool_call.get('arguments', {}))
            if risk_level == ToolRiskLevel.SAFE:
                return True  # Auto-approve safe tools
        
        # Handle both dictionary and object cases
        if isinstance(tool_call, dict):
            tool_name = tool_call.get('name', 'Unknown Tool')
            arguments = tool_call.get('arguments', {})
        else:
            tool_name = tool_call.name
            arguments = tool_call.arguments
        
        # Show enhanced preview for file operations
        if tool_name in ['write_file', 'edit_file', 'edit'] and tool:
            try:
                # Get detailed confirmation message with diff preview
                confirmation_details = await tool.get_confirmation_details(**arguments)
                if confirmation_details and hasattr(tool, '_generate_confirmation_message'):
                    detailed_message = await tool._generate_confirmation_message(**arguments)
                    self.console.print(detailed_message)
                else:
                    # Fallback to basic display
                    self._display_basic_tool_info(tool_name, arguments)
            except Exception:
                # Fallback to basic display if preview fails
                self._display_basic_tool_info(tool_name, arguments)
        else:
            # Basic display for other tools
            self._display_basic_tool_info(tool_name, arguments)

        self.console.print()

        # Use prompt_toolkit for async input
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML
        
        session = PromptSession()
        
        # Ask user for confirmation
        while True:
            try:
                response = await session.prompt_async(
                    HTML('<ansiblue><b>Allow this tool execution? (y/n/a for always): </b></ansiblue>')
                )
                response = response.lower().strip()
                
                if response in ['y', 'yes','']:
                    return True
                elif response in ['n', 'no']:
                    return False
                elif response in ['a', 'always']:
                    # Switch to YOLO mode
                    if hasattr(self, 'config'):
                        self.config.set_approval_mode(ApprovalMode.YOLO)
                        text = Text("✅ YOLO mode enabled - all future tools will be auto-approved", style="green")
                        self.console.print(text)
                    return True
                else:
                    text = Text("Please enter 'y' (yes), 'n' (no), or 'a' (always)", style="red")
                    self.console.print(text)
                    
            except KeyboardInterrupt:
                # User pressed Ctrl+C to cancel tool execution
                text = Text("\nTool execution cancelled by user (Ctrl+C)", style="yellow")
                self.console.print(text)
                return False
            except EOFError:
                # User pressed Ctrl+D or input stream ended
                text = Text("\nTool execution cancelled by user", style="yellow")
                self.console.print(text)
                return False

    def print_task_progress(self) -> None:
        """Print current task progress - display summary information only."""
        # No longer using Live display to avoid repeating all content
        # Only show execution summary at the end
        if self.agent_execution is not None and hasattr(self.agent_execution, 'status'):
            if self.agent_execution.status.value in ['success', 'failure', 'max_iterations', 'completed', 'error']:
                # Only show summary when task is completed
                summary_panel = self.create_execution_summary(self.agent_execution)
                self.console.print(summary_panel)

    def create_execution_summary(self, execution) -> Panel:
        """Display a summary of the agent execution."""
        # Create summary table
        table = Table(title="📊 Execution Summary", width=60)
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value", style="green", width=40)

        if hasattr(execution, 'status'):
            status_value = execution.status.value.title()
            status_color = "green" if execution.status.value == "success" else "red"
            status_text = Text(status_value, style=status_color)
            table.add_row("Status", status_text)
        
        if hasattr(execution, 'iterations'):
            table.add_row("Iterations", str(execution.iterations))
        
        if hasattr(execution, 'total_tokens'):
            table.add_row("Total Tokens", str(execution.total_tokens))
        
        # Show tool calls count
        if hasattr(execution, 'tool_calls'):
            table.add_row("Tool Calls", str(len(execution.tool_calls)))

        # Display final messages if available
        content = ""
        if hasattr(execution, 'get_assistant_messages'):
            messages = execution.get_assistant_messages()
            if messages:
                content = "\n".join(messages[-2:])  # Show last 2 messages
        
        if content:
            content_panel = Panel(
                content[:400] + "..." if len(content) > 400 else content,
                title="💬 Recent Messages",
                border_style="green",
                width=80
            )
            return Group(content_panel, table)
        else:
            return Group(table)

    def reset_display_tracking(self):
        """Reset display tracking state."""
        self.displayed_iterations.clear()
        self.displayed_responses.clear()
        self.displayed_tool_calls.clear()
        self.displayed_tool_results.clear()

    def gradient_line(self, text, start_color, end_color):
        """Add character-level color gradient to a line of text."""
        gradient = Text()
        length = len(text)
        for i, char in enumerate(text):
            r = int(start_color[0] + (end_color[0] - start_color[0]) * i / max(1, length - 1))
            g = int(start_color[1] + (end_color[1] - start_color[1]) * i / max(1, length - 1))
            b = int(start_color[2] + (end_color[2] - start_color[2]) * i / max(1, length - 1))
            gradient.append(char, style=f"rgb({r},{g},{b})")
        return gradient

    def show_interactive_banner(self):
        """Display gradient banner and tips."""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')

        console = self.console

        ascii_logo = [
            "                                              ",
            " ██████╗ ██╗   ██╗██╗    ██╗███████╗███╗   ██╗",
            " ██╔══██╗╚██╗ ██╔╝██║    ██║██╔════╝████╗  ██║",
            " ██████╔╝ ╚████╔╝ ██║ █╗ ██║█████╗  ██╔██╗ ██║",
            " ██╔═══╝   ╚██╔╝  ██║███╗██║██╔══╝  ██║╚██╗██║",
            " ██║        ██║   ╚███╔███╔╝███████╗██║ ╚████║",
            " ╚═╝        ╚═╝    ╚══╝╚══╝ ╚══════╝╚═╝  ╚═══╝",
            "                                              ",
        ]

        start_rgb = (102, 178, 255)  # Soft sky blue
        end_rgb   = (100, 220, 160)  # Green with blue component

        for line in ascii_logo:
            gradient = self.gradient_line(line, start_rgb, end_rgb)
            console.print(gradient)

        # Tips information
        tips = """[dim]Tips for getting started:
1. Ask questions, edit files, or run commands.
2. Be specific for the best results.
3. /help for more information. Type '/quit' to quit.[/dim]"""
        console.print(tips)
        console.print()

    def show_status_bar(self):
        """Display status bar with current directory and model info."""
        import os
        
        # Get current working directory
        current_dir = os.getcwd()
        home_dir = os.path.expanduser('~')
        
        # If in user home directory, show ~ to simplify path
        if current_dir.startswith(home_dir):
            display_dir = current_dir.replace(home_dir, '~', 1)
        else:
            display_dir = current_dir
        
        # Get model name - read latest value from config
        model_name = "qwen3-coder-plus"  # Default value
        if self.config and hasattr(self.config, 'model_config'):
            model_name = self.config.model_config.model
        elif self.config and hasattr(self.config, 'model_providers'):
            # Get model from model_providers for current provider
            default_provider = getattr(self.config, 'default_provider', 'qwen')
            if default_provider in self.config.model_providers:
                model_name = self.config.model_providers[default_provider].get('model', model_name)
        
        # Build status information
        context_percentage = max(0, 100 - (self.current_session_tokens * 100 // self.max_context_tokens))
        context_status = f"({context_percentage}% context left)"

        # Get permission status
        permission_status = ""
        try:
            if self.config and hasattr(self.config, 'get_permission_manager'):
                permission_manager = self.config.get_permission_manager()
                current_level = permission_manager.get_permission_level()

                # Create compact permission status
                permission_icons = {
                    "locked": "🔒",
                    "edit_only": "✏️",
                    "planning": "📝",
                    "yolo": "🚀"
                }
                icon = permission_icons.get(current_level.value, "❓")
                permission_status = f"  {icon} {current_level.value.upper()}"
            elif self.config:
                # Fallback to old approval mode
                approval_mode = self.config.get_approval_mode()
                if approval_mode == ApprovalMode.YOLO:
                    permission_status = "  🚀 YOLO"
                else:
                    permission_status = "  🔒 DEFAULT"
        except Exception:
            pass

        status_text = Text()
        status_text.append(display_dir, style="blue")
        status_text.append("  no sandbox (see /docs)", style="dim")
        status_text.append(f"  {model_name}", style="green")
        status_text.append(f"  {context_status}", style="dim")

        # Add permission status with appropriate color
        if permission_status:
            if "🚀" in permission_status:
                status_text.append(permission_status, style="green")
            elif "🔒" in permission_status:
                status_text.append(permission_status, style="red")
            elif "✏️" in permission_status:
                status_text.append(permission_status, style="yellow")
            elif "🧠" in permission_status:
                status_text.append(permission_status, style="blue")
            else:
                status_text.append(permission_status, style="dim")

        self.console.print(status_text)
        self.console.print()

    def start_interactive_mode(self):
        """Start interactive mode interface."""
        self.show_interactive_banner()

    def print_user_input_prompt(self):
        """Display user input prompt - now handled by prompt_toolkit."""
        pass  # prompt_toolkit handles prompt display

    def update_token_usage(self, tokens_used: int):
        """Update current session token usage."""
        self.current_session_tokens += tokens_used
        
    def set_max_context_tokens(self, max_tokens: int):
        """Set maximum context tokens for current model."""
        self.max_context_tokens = max_tokens

    def _display_basic_tool_info(self, tool_name: str, arguments: dict):
        """Display basic tool information without diff preview."""
        self.console.print(f"🔧 [bold cyan]{tool_name}[/bold cyan]")
        if arguments:
            self.console.print("Arguments:")

            # 特殊处理一些常见的长参数
            for key, value in arguments.items():
                if key == "content" and len(str(value)) > 100:
                    # 长内容只显示前100个字符
                    content_preview = str(value)[:100] + "..."
                    self.console.print(f"  [cyan]{key}[/cyan]: {content_preview}")
                else:
                    # 普通参数正常显示
                    self.console.print(f"  [cyan]{key}[/cyan]: {value}")
        else:
            self.console.print("No arguments")

    async def handle_streaming_event(self, event, agent=None):
        """Handle streaming events from agent."""
        event_type = event.get("type")
        data = event.get("data", {})

        if agent.type == "QwenAgent" or agent.type == "ClaudeCodeAgent":

            if event_type == "user_message":
                self.print(f"🔵 User:{data['message']}", "blue", True)
                self.print("")

            elif event_type == "task_continuation":
                self.print(f"🔄 Continuing Task (Turn {data['turn']}):", "yellow", True)
                self.print(f"{data['message']}")
                self.print("")

            elif event_type == "llm_stream_start":
                print("🤖 ", end="", flush=True)

            elif event_type == "llm_chunk":
                print(data["content"], end="", flush=True)

            elif event_type == "tool_result":
                self.display_tool_result(data)

            elif event_type == "waiting_for_user":
                self.print(f"💭{data['reasoning']}", "yellow")
                self.print("")
                return "waiting_for_user"

            elif event_type == "model_continues":
                self.print(f"🔄 Model continues: {data['reasoning']}", "cyan")
                if data.get('next_action'):
                    self.print(f"🎯 Next: {data['next_action'][:100]}...", "dim")
                self.print("")

            elif event_type == "task_complete":
                self.print(f"\n✅ Task completed!", "green", True)
                self.print("")
                return "task_complete"

            elif event_type == "max_turns_reached":
                self.print(f"⚠️ Maximum turns reached", "yellow", True)
                self.print("")
                return "max_turns_reached"

            elif event_type == "error":
                self.print(f"❌ Error: {data['error']}", "red")
                self.print("")
                return "error"

            elif event_type == "trajectory_saved":
                # Only show trajectory save info at task start
                if data.get('is_task_start', False):
                    self.print(f"✅ Trajectory saved to: {data['path']}", "dim")

        elif agent.type == "GeminiResearchDemo":
            if event_type == "user_message":
                self.print(f"🔵 User:{data['message']}", "blue", True)
                self.print("")
            elif event_type == "query":
                self.print(f"🔍Query: {data['queries']}", "blue")
                self.print("")
            elif event_type == "search":
                self.print(f"{data['content']}")
            elif event_type == "fetch":
                self.print(f"{data['content']}")
            elif event_type == "summary_start":
                print("\n📝Summary:", end="", flush=True)
            elif event_type == "summary_chunk":
                print(data["content"], end="", flush=True)
            elif event_type == "tool_call":
                self.print("")
                self.handle_tool_call_event(data)
            elif event_type == "tool_result":
                self.display_tool_result(data)
            elif event_type == "final_answer_start":
                print("\n📄final answer:", end="", flush=True)
            elif event_type == "final_answer_chunk":
                print(data["content"], end="", flush=True)
            elif event_type == "error":
                self.print(f"❌ Error: {data['error']}", "red")

        return None

    def display_tool_result(self, data: dict):
        """Display tool execution result."""
        if data["success"]:
            tool_name = data.get('name', 'Tool')
            result = data.get('result', '')

            # Enhanced result display with highlighted content for file operations
            if isinstance(result, dict) and result.get('operation') in ['write_file', 'edit_file']:
                panel = create_enhanced_tool_result_display(result, tool_name)
            else:
                # Simple result display for other tools
                panel = Panel(
                    Text(str(result)),
                    title=f"✓ {tool_name}",
                    title_align="left",
                    border_style="green",
                    padding=(0, 1)
                )

            self.console.print(panel)
        else:
            # Error case with red border
            tool_name = data.get('name', 'Tool')
            error = data.get('error', 'Unknown error')

            panel = Panel(
                str(error),
                title=f"✗ {tool_name}",
                title_align="left",
                border_style="red",
                padding=(0, 1)
            )
            self.console.print(panel)

    def handle_tool_call_event(self, data: dict):
        """Handle tool call event display."""
        tool_call = data.get('tool_call', None)
        tool_name = tool_call.name
        arguments = tool_call.arguments

        # Special handling for bash tool to show specific command
        if tool_name == "bash" and "command" in arguments:
            command = arguments["command"]

            # Create framed bash command display
            panel = Panel(
                f"[cyan]{command}[/cyan]",
                title=f"🔧 {tool_name}",
                title_align="left",
                border_style="yellow",
                padding=(0, 1)
            )
            self.console.print(panel)
        else:
            # Normal display for other tools
            args_str = str(arguments)
            panel = Panel(
                args_str,
                title=f"🔧 {tool_name}",
                title_align="left",
                border_style="yellow",
                padding=(0, 1)
            )
            self.console.print(panel)

