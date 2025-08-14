"""Stats command implementation."""

from typing import Dict, Any
from rich.panel import Panel
from rich.console import Console
from rich.table import Table
from .base_command import BaseCommand
from pywen.core.session_stats import session_stats


class StatsCommand(BaseCommand):
    """Display session statistics."""
    
    def __init__(self):
        super().__init__(
            name="stats",
            description="Display session statistics including token usage, API calls, and tool usage",
            alt_name="statistics"
        )
        self.console = Console()
    
    async def execute(self, context: Dict[str, Any], args: str) -> bool:
        """Execute the stats command."""
        args = args.strip().lower()
        
        if args in ["model", "models"]:
            panel = self._get_model_stats_panel()
        elif args in ["tool", "tools"]:
            panel = self._get_tool_stats_panel()
        elif args in ["api"]:
            panel = self._get_api_stats_panel()
        elif args in ["token", "tokens"]:
            panel = self._get_token_stats_panel()
        elif args in ["agent", "agents"]:
            panel = self._get_agent_stats_panel()
        elif args in ["all", "session"]:
            panel = self._get_summary_panel()
        else:
            # Default: show current agent stats if available, otherwise show summary
            panel = self._get_current_agent_stats_panel()
        
        self.console.print(panel)
        return True
    
    def _get_summary_panel(self) -> Panel:
        """Get formatted statistics summary panel."""
        content = []
        
        # Session info
        content.append(f"[bold cyan]Session Duration:[/bold cyan] {session_stats.session_duration}")
        content.append(f"[bold cyan]Started:[/bold cyan] {session_stats.session_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        content.append("")
        
        # API Stats
        content.append("[bold blue]🔗 API Statistics[/bold blue]")
        content.append(f"  Total Requests: [green]{session_stats.api.total_requests}[/green]")
        content.append(f"  Total Errors: [red]{session_stats.api.total_errors}[/red]")
        content.append(f"  Error Rate: [yellow]{session_stats.api.error_rate:.1f}%[/yellow]")
        content.append("")
        
        # Token Stats
        if session_stats.tokens.total_tokens > 0:
            content.append("[bold yellow]🎯 Token Usage[/bold yellow]")
            content.append(f"  Total: [green]{session_stats.tokens.total_tokens:,}[/green]")
            content.append(f"  Input: [cyan]{session_stats.tokens.input_tokens:,}[/cyan]")
            content.append(f"  Output: [magenta]{session_stats.tokens.output_tokens:,}[/magenta]")
            if session_stats.tokens.cached_tokens > 0:
                cache_rate = (session_stats.tokens.cached_tokens / session_stats.tokens.input_tokens * 100) if session_stats.tokens.input_tokens > 0 else 0
                content.append(f"  Cached: [blue]{session_stats.tokens.cached_tokens:,} ({cache_rate:.1f}%)[/blue]")
            if session_stats.tokens.reasoning_tokens > 0:
                content.append(f"  Reasoning: [dim]{session_stats.tokens.reasoning_tokens:,}[/dim]")
            content.append("")
        
        # Tool Stats
        if session_stats.tools.total_calls > 0:
            content.append("[bold green]🛠️ Tool Usage[/bold green]")
            content.append(f"  Total Calls: [green]{session_stats.tools.total_calls}[/green]")
            content.append(f"  Success Rate: [yellow]{session_stats.tools.success_rate:.1f}%[/yellow]")
            
            if session_stats.tools.by_name:
                content.append("  [dim]Tool Breakdown:[/dim]")
                for tool_name, stats in sorted(session_stats.tools.by_name.items()):
                    success_rate = (stats['success'] / stats['calls'] * 100) if stats['calls'] > 0 else 0
                    content.append(f"    [cyan]{tool_name}[/cyan]: {stats['calls']} calls, {success_rate:.1f}% success")
            content.append("")
        
        # Model Stats
        if session_stats.models_used:
            content.append("[bold blue]🤖 Model Usage[/bold blue]")
            for model, stats in session_stats.models_used.items():
                content.append(f"  [cyan]{model}[/cyan]:")
                content.append(f"    Total: [green]{stats.total_tokens:,}[/green] tokens")
                content.append(f"    Input: [yellow]{stats.input_tokens:,}[/yellow], Output: [magenta]{stats.output_tokens:,}[/magenta]")
                if stats.cached_tokens > 0:
                    content.append(f"    Cached: [blue]{stats.cached_tokens:,}[/blue]")
            content.append("")
        
        full_content = "\n".join(content)
        return Panel(full_content, title="📊 Session Statistics", border_style="blue", padding=(1, 2))
    
    def _get_model_stats_panel(self) -> Panel:
        """Get detailed model statistics panel."""
        if not session_stats.models_used:
            content = "[yellow]No models used in this session.[/yellow]"
        else:
            table = Table(show_header=True, header_style="bold blue")
            table.add_column("Model", style="cyan")
            table.add_column("Total Tokens", style="green", justify="right")
            table.add_column("Input", style="yellow", justify="right")
            table.add_column("Output", style="magenta", justify="right")
            table.add_column("Cached", style="blue", justify="right")
            
            for model, stats in session_stats.models_used.items():
                cached_display = f"{stats.cached_tokens:,}" if stats.cached_tokens > 0 else "-"
                table.add_row(
                    model,
                    f"{stats.total_tokens:,}",
                    f"{stats.input_tokens:,}",
                    f"{stats.output_tokens:,}",
                    cached_display
                )
            content = table
        
        return Panel(content, title="🤖 Model Statistics", border_style="blue", padding=(1, 2))
    
    def _get_tool_stats_panel(self) -> Panel:
        """Get detailed tool statistics panel."""
        if session_stats.tools.total_calls == 0:
            content = "[yellow]No tools used in this session.[/yellow]"
        else:
            # Summary info
            summary = f"[bold]Total Calls:[/bold] {session_stats.tools.total_calls}\n"
            summary += f"[bold]Success Rate:[/bold] {session_stats.tools.success_rate:.1f}%\n"
            
            if session_stats.tools.by_name:
                table = Table(show_header=True, header_style="bold green")
                table.add_column("Tool", style="cyan")
                table.add_column("Calls", style="green", justify="right")
                table.add_column("Success", style="green", justify="right")
                table.add_column("Failures", style="red", justify="right")
                table.add_column("Success Rate", style="yellow", justify="right")
                
                for tool_name, stats in sorted(session_stats.tools.by_name.items()):
                    success_rate = (stats['success'] / stats['calls'] * 100) if stats['calls'] > 0 else 0
                    table.add_row(
                        tool_name,
                        str(stats['calls']),
                        str(stats['success']),
                        str(stats['failures']),
                        f"{success_rate:.1f}%",
                    )
                content = summary + str(table)
            else:
                content = summary
        
        return Panel(content, title="🛠️ Tool Statistics", border_style="green", padding=(1, 2))
    
    def _get_api_stats_panel(self) -> Panel:
        """Get detailed API statistics panel."""
        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total Requests", str(session_stats.api.total_requests))
        table.add_row("Total Errors", str(session_stats.api.total_errors))
        table.add_row("Error Rate", f"{session_stats.api.error_rate:.1f}%")
        
        return Panel(table, title="🔗 API Statistics", border_style="blue", padding=(1, 2))
    
    def _get_token_stats_panel(self) -> Panel:
        """Get detailed token statistics panel."""
        if session_stats.tokens.total_tokens == 0:
            content = "[yellow]No tokens used in this session.[/yellow]"
        else:
            table = Table(show_header=True, header_style="bold yellow")
            table.add_column("Token Type", style="cyan")
            table.add_column("Count", style="green", justify="right")
            table.add_column("Percentage", style="yellow", justify="right")
            
            total = session_stats.tokens.total_tokens
            table.add_row("Total", f"{total:,}", "100.0%")
            
            input_pct = (session_stats.tokens.input_tokens / total * 100) if total > 0 else 0
            table.add_row("Input", f"{session_stats.tokens.input_tokens:,}", f"{input_pct:.1f}%")
            
            output_pct = (session_stats.tokens.output_tokens / total * 100) if total > 0 else 0
            table.add_row("Output", f"{session_stats.tokens.output_tokens:,}", f"{output_pct:.1f}%")
            
            if session_stats.tokens.cached_tokens > 0:
                cached_pct = (session_stats.tokens.cached_tokens / session_stats.tokens.input_tokens * 100) if session_stats.tokens.input_tokens > 0 else 0
                table.add_row("Cached", f"{session_stats.tokens.cached_tokens:,}", f"{cached_pct:.1f}%")
            
            if session_stats.tokens.reasoning_tokens > 0:
                reasoning_pct = (session_stats.tokens.reasoning_tokens / total * 100) if total > 0 else 0
                table.add_row("Reasoning", f"{session_stats.tokens.reasoning_tokens:,}", f"{reasoning_pct:.1f}%")
            
            content = table
        
        return Panel(content, title="🎯 Token Statistics", border_style="yellow", padding=(1, 2))

    def _get_agent_stats_panel(self) -> Panel:
        """Get detailed agent statistics panel."""
        if not session_stats.agents:
            content = "[yellow]No agent statistics available.[/yellow]"
        else:
            content = []

            # Session info
            content.append(f"[bold cyan]Current Agent:[/bold cyan] {session_stats.current_agent or 'None'}")
            content.append(f"[bold cyan]Session Duration:[/bold cyan] {session_stats.session_duration}")
            content.append("")

            # Agent breakdown
            content.append("[bold magenta]🤖 Agent Statistics[/bold magenta]")

            for agent_name, agent_stats in sorted(session_stats.agents.items()):
                content.append(f"\n[bold cyan]{agent_name}[/bold cyan]")
                content.append(f"  Tasks: [green]{agent_stats.total_tasks}[/green]")
                content.append(f"  First used: [dim]{agent_stats.first_used.strftime('%H:%M:%S')}[/dim]")
                content.append(f"  Last used: [dim]{agent_stats.last_used.strftime('%H:%M:%S')}[/dim]")

                # API stats
                if agent_stats.api.total_requests > 0:
                    content.append(f"  API Requests: [green]{agent_stats.api.total_requests}[/green]")
                    if agent_stats.api.total_errors > 0:
                        content.append(f"  API Errors: [red]{agent_stats.api.total_errors}[/red] ({agent_stats.api.error_rate:.1f}%)")

                # Token stats
                if agent_stats.tokens.total_tokens > 0:
                    content.append(f"  Total Tokens: [yellow]{agent_stats.tokens.total_tokens:,}[/yellow]")
                    content.append(f"    Input: [cyan]{agent_stats.tokens.input_tokens:,}[/cyan], Output: [magenta]{agent_stats.tokens.output_tokens:,}[/magenta]")
                    if agent_stats.tokens.cached_tokens > 0:
                        cache_rate = (agent_stats.tokens.cached_tokens / agent_stats.tokens.input_tokens * 100) if agent_stats.tokens.input_tokens > 0 else 0
                        content.append(f"    Cached: [blue]{agent_stats.tokens.cached_tokens:,} ({cache_rate:.1f}%)[/blue]")

                # Tool stats
                if agent_stats.tools.total_calls > 0:
                    content.append(f"  Tool Calls: [green]{agent_stats.tools.total_calls}[/green] ({agent_stats.tools.success_rate:.1f}% success)")

                    # Top 3 tools
                    if agent_stats.tools.by_name:
                        top_tools = sorted(agent_stats.tools.by_name.items(), key=lambda x: x[1]['calls'], reverse=True)[:3]
                        tool_list = []
                        for tool_name, stats in top_tools:
                            tool_list.append(f"{tool_name}({stats['calls']})")
                        content.append(f"    Top tools: [dim]{', '.join(tool_list)}[/dim]")

                # Model stats
                if agent_stats.models_used:
                    model_list = []
                    for model, stats in agent_stats.models_used.items():
                        model_list.append(f"{model}({stats.total_tokens:,})")
                    content.append(f"  Models: [dim]{', '.join(model_list)}[/dim]")

            content = "\n".join(content)

        return Panel(content, title="🤖 Agent Statistics", border_style="magenta", padding=(1, 2))

    def _get_current_agent_stats_panel(self) -> Panel:
        """Get statistics for the current active agent."""
        current_agent = session_stats.current_agent

        if not current_agent or current_agent not in session_stats.agents:
            # Fallback to session summary if no current agent
            return self._get_summary_panel()

        agent_stats = session_stats.agents[current_agent]
        content = []

        # Agent header
        content.append(f"[bold cyan]Current Agent: {current_agent}[/bold cyan]")
        content.append(f"Session Duration: [dim]{session_stats.session_duration}[/dim]")
        content.append("")

        # Tasks
        content.append(f"[bold green]📋 Tasks Completed: {agent_stats.total_tasks}[/bold green]")
        content.append(f"First used: [dim]{agent_stats.first_used.strftime('%H:%M:%S')}[/dim]")
        content.append(f"Last used: [dim]{agent_stats.last_used.strftime('%H:%M:%S')}[/dim]")
        content.append("")

        # API stats
        if agent_stats.api.total_requests > 0:
            content.append("[bold blue]🔗 API Statistics[/bold blue]")
            content.append(f"  Total Requests: [green]{agent_stats.api.total_requests}[/green]")
            if agent_stats.api.total_errors > 0:
                content.append(f"  Errors: [red]{agent_stats.api.total_errors}[/red] ({agent_stats.api.error_rate:.1f}%)")
            else:
                content.append(f"  Error Rate: [green]0.0%[/green]")
            content.append("")

        # Token stats
        if agent_stats.tokens.total_tokens > 0:
            content.append("[bold yellow]🎯 Token Usage[/bold yellow]")
            content.append(f"  Total: [yellow]{agent_stats.tokens.total_tokens:,}[/yellow]")
            content.append(f"  Input: [cyan]{agent_stats.tokens.input_tokens:,}[/cyan]")
            content.append(f"  Output: [magenta]{agent_stats.tokens.output_tokens:,}[/magenta]")

            if agent_stats.tokens.cached_tokens > 0:
                cache_rate = (agent_stats.tokens.cached_tokens / agent_stats.tokens.input_tokens * 100) if agent_stats.tokens.input_tokens > 0 else 0
                content.append(f"  Cached: [blue]{agent_stats.tokens.cached_tokens:,} ({cache_rate:.1f}%)[/blue]")

            if agent_stats.tokens.reasoning_tokens > 0:
                content.append(f"  Reasoning: [purple]{agent_stats.tokens.reasoning_tokens:,}[/purple]")
            content.append("")

        # Tool stats
        if agent_stats.tools.total_calls > 0:
            content.append("[bold green]🛠️ Tool Usage[/bold green]")
            content.append(f"  Total Calls: [green]{agent_stats.tools.total_calls}[/green]")
            content.append(f"  Success Rate: [green]{agent_stats.tools.success_rate:.1f}%[/green]")

            if agent_stats.tools.by_name:
                content.append("  Tool Breakdown:")
                # Show all tools used by this agent
                for tool_name, stats in sorted(agent_stats.tools.by_name.items(), key=lambda x: x[1]['calls'], reverse=True):
                    success_rate = (stats['success'] / stats['calls'] * 100) if stats['calls'] > 0 else 0
                    content.append(f"    {tool_name}: [cyan]{stats['calls']} calls[/cyan], [green]{success_rate:.1f}% success[/green]")
            content.append("")

        # Model stats
        if agent_stats.models_used:
            content.append("[bold purple]🤖 Model Usage[/bold purple]")
            for model, stats in agent_stats.models_used.items():
                content.append(f"  {model}:")
                content.append(f"    Total: [yellow]{stats.total_tokens:,} tokens[/yellow]")
                content.append(f"    Input: [cyan]{stats.input_tokens:,}[/cyan], Output: [magenta]{stats.output_tokens:,}[/magenta]")
                if stats.cached_tokens > 0:
                    cache_rate = (stats.cached_tokens / stats.input_tokens * 100) if stats.input_tokens > 0 else 0
                    content.append(f"    Cached: [blue]{stats.cached_tokens:,} ({cache_rate:.1f}%)[/blue]")

        content_str = "\n".join(content)
        return Panel(content_str, title=f"📊 {current_agent} Statistics", border_style="cyan", padding=(1, 2))
    
    def get_help(self) -> str:
        """Get help text for the stats command."""
        return """
Usage: /stats [subcommand]

Display session statistics including token usage, API calls, and tool usage.

Subcommands:
  (none)    - Show current agent statistics
  all       - Show complete session statistics summary
  model     - Show detailed model usage statistics
  tools     - Show detailed tool usage statistics
  api       - Show detailed API call statistics
  tokens    - Show detailed token usage statistics
  agents    - Show detailed agent usage statistics

Examples:
  /stats           # Show current agent stats
  /stats all       # Show complete session summary
  /stats model     # Show model-specific stats
  /stats tools     # Show tool usage breakdown
  /stats agents    # Show all agent stats
"""
