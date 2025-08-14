"""Command line interface for Qwen Python Agent."""

import argparse
import asyncio
import os
import sys
import uuid
import threading

from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

from pywen.config.config import ApprovalMode
from pywen.config.loader import create_default_config, load_config_with_cli_overrides
from pywen.agents.qwen.qwen_agent import QwenAgent
from pywen.ui.cli_console import CLIConsole
from pywen.ui.command_processor import CommandProcessor
from pywen.ui.utils.keyboard import create_key_bindings
from pywen.ui.highlighted_content import create_enhanced_tool_result_display


def generate_session_id() -> str:
    """Generate session ID using short UUID."""
    return str(uuid.uuid4())[:8]


def main_sync():
    """Synchronous wrapper for the main CLI entry point."""
    asyncio.run(main())


async def main():
    """Main CLI entry point."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Pywen Python Agent")
    parser.add_argument("--config", type=str, default="pywen_config.json", help="Config file path")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--model", type=str, help="Override model name")
    parser.add_argument("--temperature", type=float, help="Override temperature")
    parser.add_argument("--max-tokens", type=int, help="Override max tokens")
    parser.add_argument("--create-config", action="store_true", help="Create default config file")
    parser.add_argument("--session-id", type=str, help="Use specific session ID")
    parser.add_argument("prompt", nargs="?", help="Prompt to execute")
    
    args = parser.parse_args()
    
    # Generate or use specified session ID
    session_id = args.session_id or generate_session_id()
    
    # Handle config creation
    if args.create_config:
        create_default_config(args.config)
        return
    
    # Check if config exists and is valid
    if not os.path.exists(args.config):
        from pywen.ui.config_wizard import ConfigWizard
        wizard = ConfigWizard()
        wizard.run()
        
        # After wizard completes, check if config was created
        if not os.path.exists(args.config):
            console = Console()
            console.print("Configuration was not created. Exiting.", color="red")
            sys.exit(1)
    
    # Load configuration
    try:
        config = load_config_with_cli_overrides(args.config, args)
        config.session_id = session_id
    except Exception as e:
        console = Console()
        console.print(f"Error loading configuration: {e}", color="red")
        console.print("Configuration may be invalid. Starting configuration wizard...", color="yellow")
        
        # Import and run config wizard
        from pywen.ui.config_wizard import ConfigWizard
        wizard = ConfigWizard()
        wizard.run()
        
        # Try loading config again
        try:
            config = load_config_with_cli_overrides(args.config, args)
            config.session_id = session_id
        except Exception as e2:
            console.print(f"Still unable to load configuration: {e2}", color="red")
            sys.exit(1)
    
    # Create console and agent
    console = CLIConsole(config)
    console.config = config
    
    agent = QwenAgent(config)
    agent.set_cli_console(console)
    
    # Display current mode
    mode_status = "🚀 YOLO" if config.get_approval_mode() == ApprovalMode.YOLO else "🔒 CONFIRM"
    console.print(f"Mode: {mode_status} (Ctrl+Y to toggle)")

    # Start interactive interface
    console.start_interactive_mode()

    # Run in appropriate mode
    if args.interactive or not args.prompt:
        await interactive_mode_streaming(agent, console, session_id)
    else:
        await single_prompt_mode_streaming(agent, console, args.prompt)


async def interactive_mode_streaming(agent: QwenAgent, console: CLIConsole, session_id: str):
    """Run agent in interactive mode with streaming using prompt_toolkit."""
    
    # Create command processor and history
    command_processor = CommandProcessor()
    history = InMemoryHistory()
    
    # Track task execution state
    in_task_execution = False
    cancel_event = threading.Event()
    current_task = None
    current_agent = agent  # 添加这行：跟踪当前agent
    
    # Create key bindings
    bindings = create_key_bindings(
        lambda: console, 
        lambda: cancel_event, 
        lambda: current_task
    )
    
    # Create prompt session
    session = PromptSession(
        history=history,
        auto_suggest=AutoSuggestFromHistory(),
        key_bindings=bindings,
        multiline=True,
        wrap_lines=True,
    )

    # Main interaction loop
    while True:
        try:
            # Show status bar only when not in task execution
            if not in_task_execution:
                console.show_status_bar()
            
            # Get user input with session ID
            try:
                user_input = await session.prompt_async(
                    HTML(f'<ansiblue>✦</ansiblue><ansigreen>{session_id}</ansigreen> <ansiblue>❯</ansiblue> '),
                    multiline=False,
                )
            except EOFError:
                console.print("\nGoodbye!", "yellow")
                break
            except KeyboardInterrupt:
                console.print("\nUse Ctrl+C twice to quit, or type 'exit'", "yellow")
                continue
            
            # Check if user_input is None (app exit)
            if user_input is None:
                console.print("\nGoodbye!", "yellow")
                break
                
            user_input = user_input.strip()
            
            # Check exit commands
            if user_input.lower() in ['exit', 'quit', 'q']:
                console.print("Goodbye!", "yellow")
                break
            
            if not user_input:
                continue
            
            # Handle shell commands (!)
            if user_input.startswith('!'):
                context = {'console': console, 'agent': current_agent}
                await command_processor._handle_shell_command(user_input, context)
                continue
            
            # Handle slash commands (/)
            context = {'console': console, 'agent': current_agent, 'config': console.config} 
            command_result = await command_processor.process_command(user_input, context)
            
            # 添加这段：检查agent是否被切换
            if command_result and 'agent' in context and context['agent'] != current_agent:
                current_agent = context['agent']
            
            if command_result:
                continue
            
            # Reset display tracking and enter task execution
            console.reset_display_tracking()
            # Reset Claude agent start flag for new conversation
            if hasattr(console, '_claude_started'):
                delattr(console, '_claude_started')
            in_task_execution = True
            cancel_event.clear()
            
            # Execute user request
            try:
                current_task = asyncio.create_task(
                    execute_streaming_with_cancellation(current_agent, user_input, console, cancel_event)  
                )
                
                result = await current_task
                
                # Handle result and update task execution state
                if result == "waiting_for_user":
                    # Keep task execution state, wait for user input
                    continue
                elif result in ["task_complete", "max_turns_reached", "completed"]:
                    # Task completed, exit task execution state
                    in_task_execution = False
                    current_task = None
                    cancel_event.clear()
                else:
                    # Other cases (cancelled, error, etc.)
                    in_task_execution = False
                    current_task = None
                    cancel_event.clear()
            
            except asyncio.CancelledError:
                console.print("\n⚠️ Operation cancelled by user",color="yellow")
            except UnicodeError as e:
                console.print(f"Unicode 错误: {e}", "red")
                continue
            except KeyboardInterrupt:
                console.print("\n⚠️ Operation interrupted by user",color="yellow")
                if current_task and not current_task.done():
                    current_task.cancel()
            finally:
                # Reset task execution state
                in_task_execution = False
                current_task = None
                cancel_event.clear()

        except KeyboardInterrupt:
            console.print("\nInterrupted by user. Press Ctrl+C again to quit.", "yellow")
            in_task_execution = False
        except EOFError:
            console.print("\nGoodbye!", "yellow")
            break
        except UnicodeError as e:
            console.print(f"Unicode 错误: {e}", "red")
            continue
        except Exception as e:
            console.print(f"Error: {e}", "red")
            in_task_execution = False


async def execute_streaming_with_cancellation(agent, user_input, console, cancel_event):
    """Execute streaming task with cancellation support."""
    try:
        async for event in agent.run(user_input):
            # Check if cancelled
            if cancel_event.is_set():
                console.print("\n⚠️ Operation cancelled by user",color="yellow")
                return "cancelled"
            
            # Handle streaming event
            result = await handle_streaming_event(event, console, agent)
            
            if result == "tool_cancelled":
                return "tool_cancelled"

            # Return specific states to main loop
            if result in ["task_complete", "max_turns_reached", "waiting_for_user"]:
                return result
            
            # Handle errors
            if event.get("type") == "error":
                return "error"
        
        return "completed"
        
    except asyncio.CancelledError:
        console.print("\n⚠️ Task was cancelled","yellow")
        return "cancelled"
    except Exception as e:
        console.print(f"\nError: {e}","red")
        return "error"


async def handle_streaming_event(event, console, agent=None):
    """Handle streaming events from agent."""
    event_type = event.get("type")
    data = event.get("data", {})

    if agent.type == "QwenAgent" or agent.type == "ClaudeCodeAgent":

        if event_type == "user_message":
            console.print(f"🔵 User:{data['message']}","blue",True)
            console.print("")

        elif event_type == "task_continuation":
            console.print(f"🔄 Continuing Task (Turn {data['turn']}):","yellow",True)
            console.print(f"{data['message']}")
            console.print("")

        elif event_type == "llm_stream_start":
            print("🤖 ", end="", flush=True)

        elif event_type == "llm_chunk":
            print(data["content"], end="", flush=True)

        elif event_type == "tool_result":
            display_tool_result(data, console)

        elif event_type == "waiting_for_user":
            console.print(f"💭{data['reasoning']}","yellow")
            console.print("")
            return "waiting_for_user"

        elif event_type == "model_continues":
            console.print(f"🔄 Model continues: {data['reasoning']}","cyan")
            if data.get('next_action'):
                console.print(f"🎯 Next: {data['next_action'][:100]}...","dim")
            console.print("")

        elif event_type == "task_complete":
            console.print(f"\n✅ Task completed!","green",True)
            console.print("")
            return "task_complete"

        elif event_type == "max_turns_reached":
            console.print(f"⚠️ Maximum turns reached","yellow",True)
            console.print("")
            return "max_turns_reached"

        elif event_type == "error":
            console.print(f"❌ Error: {data['error']}","red")
            console.print("")
            return "error"

        elif event_type == "trajectory_saved":
            # Only show trajectory save info at task start
            if data.get('is_task_start', False):
                console.print(f"✅ Trajectory saved to: {data['path']}","dim")


    elif agent.type == "GeminiResearchDemo":
        if event_type == "user_message":
            console.print(f"🔵 User:{data['message']}","blue", True)
            console.print("")
        elif event_type == "query":
            console.print(f"🔍Query: {data['queries']}","blue")
            console.print("")
        elif event_type == "search":
            console.print(f"{data['content']}")
        elif event_type == "fetch":
            console.print(f"{data['content']}")
        elif event_type == "summary_start":
            print("\n📝Summary:", end="", flush=True)
        elif event_type == "summary_chunk":
            print(data["content"], end="", flush=True)
        elif event_type == "tool_call":
            console.print("")
            handle_tool_call_event(data, console)
        elif event_type == "tool_result":
            display_tool_result(data, console)
        elif event_type == "final_answer_start":
            print("\n📄final answer:", end="", flush=True)
        elif event_type == "final_answer_chunk":
            print(data["content"], end="", flush=True)
        elif event_type == "error":
            console.print(f"❌ Error: {data['error']}",color="red")



    return None


def display_tool_result(data: dict, console: CLIConsole):
    """Display tool execution result."""
    if data["success"]:
        from rich.panel import Panel
        from rich.text import Text

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

        console.console.print(panel)
    else:
        # Error case with red border
        from rich.panel import Panel
        tool_name = data.get('name', 'Tool')
        error = data.get('error', 'Unknown error')
        
        panel = Panel(
            str(error),
            title=f"✗ {tool_name}",
            title_align="left", 
            border_style="red",
            padding=(0, 1)
        )
        console.console.print(panel)


def handle_tool_call_event(data: dict, console: CLIConsole):
    """Handle tool call event display."""
    tool_call = data.get('tool_call', None)
    tool_name = tool_call.name
    arguments = tool_call.arguments
    
    # Special handling for bash tool to show specific command
    if tool_name == "bash" and "command" in arguments:
        command = arguments["command"]
        
        # Create framed bash command display
        from rich.panel import Panel
        panel = Panel(
            f"[cyan]{command}[/cyan]",
            title=f"🔧 {tool_name}",
            title_align="left",
            border_style="yellow",
            padding=(0, 1)
        )
        console.console.print(panel)
    else:
        # Normal display for other tools
        args_str = str(arguments)
        from rich.panel import Panel
        panel = Panel(
            args_str,
            title=f"🔧 {tool_name}",
            title_align="left",
            border_style="yellow", 
            padding=(0, 1)
        )
        console.console.print(panel)


async def single_prompt_mode_streaming(agent, console: CLIConsole, prompt_text: str):
    """Run agent in single prompt mode with streaming."""

    # Reset display tracking
    console.reset_display_tracking()
    # Reset Claude agent start flag for new conversation
    if hasattr(console, '_claude_started'):
        delattr(console, '_claude_started')

    # Execute user request
    async for event in agent.run(prompt_text):
        # Handle streaming events
        await handle_streaming_event(event, console, agent)

if __name__ == "__main__":
    main_sync()
