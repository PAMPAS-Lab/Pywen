"""Session statistics tracking for Pywen."""

from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class TokenStats:
    """Token usage statistics."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class APIStats:
    """API call statistics."""
    total_requests: int = 0
    total_errors: int = 0
    
    @property
    def error_rate(self) -> float:
        return (self.total_errors / self.total_requests * 100) if self.total_requests > 0 else 0


@dataclass
class ToolStats:
    """Tool usage statistics."""
    total_calls: int = 0
    total_success: int = 0
    total_failures: int = 0
    by_name: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return (self.total_success / self.total_calls * 100) if self.total_calls > 0 else 0


@dataclass
class AgentStats:
    """Statistics for a specific agent."""
    name: str
    tokens: TokenStats = field(default_factory=TokenStats)
    api: APIStats = field(default_factory=APIStats)
    tools: ToolStats = field(default_factory=ToolStats)
    models_used: Dict[str, TokenStats] = field(default_factory=dict)
    first_used: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    total_tasks: int = 0
    


class SessionStats:
    """Tracks statistics for the entire session."""

    def __init__(self):
        self.session_start_time = datetime.now()
        self.tokens = TokenStats()
        self.api = APIStats()
        self.tools = ToolStats()
        self.models_used: Dict[str, TokenStats] = {}
        self.agents: Dict[str, AgentStats] = {}
        self.current_agent: Optional[str] = None

    def set_current_agent(self, agent_name: str):
        """Set the current active agent."""
        self.current_agent = agent_name
        if agent_name not in self.agents:
            self.agents[agent_name] = AgentStats(name=agent_name)
        else:
            self.agents[agent_name].last_used = datetime.now()

    def record_llm_interaction(self, provider: str, model: str, usage: Optional[Any], error: bool = False, agent_name: Optional[str] = None):
        """Record an LLM API interaction."""
        # Use current agent if not specified
        if agent_name is None:
            agent_name = self.current_agent

        # Update global stats
        self.api.total_requests += 1

        if error:
            self.api.total_errors += 1
            # Also update agent stats if available
            if agent_name and agent_name in self.agents:
                self.agents[agent_name].api.total_requests += 1
                self.agents[agent_name].api.total_errors += 1
            return

        if usage:
            input_tokens = getattr(usage, 'input_tokens', 0) or 0
            output_tokens = getattr(usage, 'output_tokens', 0) or 0
            total_tokens = getattr(usage, 'total_tokens', 0) or input_tokens + output_tokens
            cached_tokens = getattr(usage, 'cached_tokens', 0) or 0
            reasoning_tokens = getattr(usage, 'reasoning_tokens', 0) or 0

            # Update global stats
            self.tokens.input_tokens += input_tokens
            self.tokens.output_tokens += output_tokens
            self.tokens.total_tokens += total_tokens
            self.tokens.cached_tokens += cached_tokens
            self.tokens.reasoning_tokens += reasoning_tokens

            # Update per-model stats
            if model not in self.models_used:
                self.models_used[model] = TokenStats()

            model_stats = self.models_used[model]
            model_stats.input_tokens += input_tokens
            model_stats.output_tokens += output_tokens
            model_stats.total_tokens += total_tokens
            model_stats.cached_tokens += cached_tokens
            model_stats.reasoning_tokens += reasoning_tokens

            # Update agent-specific stats
            if agent_name:
                # Ensure agent exists in the dictionary
                if agent_name not in self.agents:
                    self.agents[agent_name] = AgentStats(name=agent_name)
                agent_stats = self.agents[agent_name]
                agent_stats.api.total_requests += 1
                agent_stats.last_used = datetime.now()

                # Update agent token stats
                agent_stats.tokens.input_tokens += input_tokens
                agent_stats.tokens.output_tokens += output_tokens
                agent_stats.tokens.total_tokens += total_tokens
                agent_stats.tokens.cached_tokens += cached_tokens
                agent_stats.tokens.reasoning_tokens += reasoning_tokens

                # Update agent per-model stats
                if model not in agent_stats.models_used:
                    agent_stats.models_used[model] = TokenStats()

                agent_model_stats = agent_stats.models_used[model]
                agent_model_stats.input_tokens += input_tokens
                agent_model_stats.output_tokens += output_tokens
                agent_model_stats.total_tokens += total_tokens
                agent_model_stats.cached_tokens += cached_tokens
                agent_model_stats.reasoning_tokens += reasoning_tokens

    def record_tool_call(self, tool_name: str, success: bool, agent_name: Optional[str] = None):
        """Record a tool call."""
        # Use current agent if not specified
        if agent_name is None:
            agent_name = self.current_agent

        # Update global stats
        self.tools.total_calls += 1

        if success:
            self.tools.total_success += 1
        else:
            self.tools.total_failures += 1

        # Update per-tool stats
        if tool_name not in self.tools.by_name:
            self.tools.by_name[tool_name] = {
                'calls': 0,
                'success': 0,
                'failures': 0,
            }

        tool_stats = self.tools.by_name[tool_name]
        tool_stats['calls'] += 1

        if success:
            tool_stats['success'] += 1
        else:
            tool_stats['failures'] += 1

        # Update agent-specific stats
        if agent_name:
            # Ensure agent exists in the dictionary
            if agent_name not in self.agents:
                self.agents[agent_name] = AgentStats(name=agent_name)
            agent_stats = self.agents[agent_name]
            agent_stats.tools.total_calls += 1
            agent_stats.last_used = datetime.now()

            if success:
                agent_stats.tools.total_success += 1
            else:
                agent_stats.tools.total_failures += 1

            # Update agent per-tool stats
            if tool_name not in agent_stats.tools.by_name:
                agent_stats.tools.by_name[tool_name] = {
                    'calls': 0,
                    'success': 0,
                    'failures': 0,
                }

            agent_tool_stats = agent_stats.tools.by_name[tool_name]
            agent_tool_stats['calls'] += 1

            if success:
                agent_tool_stats['success'] += 1
            else:
                agent_tool_stats['failures'] += 1

    def record_task_start(self, agent_name: Optional[str] = None):
        """Record the start of a new task."""
        if agent_name is None:
            agent_name = self.current_agent

        if agent_name:
            # Ensure agent exists in the dictionary
            if agent_name not in self.agents:
                self.agents[agent_name] = AgentStats(name=agent_name)

            self.agents[agent_name].total_tasks += 1
            self.agents[agent_name].last_used = datetime.now()
    
    @property
    def session_duration(self) -> str:
        """Get formatted session duration."""
        delta = datetime.now() - self.session_start_time
        total_seconds = int(delta.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    def get_stats_summary(self) -> str:
        """Get formatted statistics summary."""
        lines = []
        
        # Session info
        lines.append(f"[bold cyan]Session Duration:[/bold cyan] {self.session_duration}")
        lines.append(f"[bold cyan]Started:[/bold cyan] {self.session_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # API Stats
        lines.append("[bold blue]🔗 API Statistics[/bold blue]")
        lines.append(f"  Total Requests: [green]{self.api.total_requests}[/green]")
        lines.append(f"  Total Errors: [red]{self.api.total_errors}[/red]")
        lines.append(f"  Error Rate: [yellow]{self.api.error_rate:.1f}%[/yellow]")
        lines.append("")
        
        # Token Stats
        if self.tokens.total_tokens > 0:
            lines.append("[bold yellow]🎯 Token Usage[/bold yellow]")
            lines.append(f"  Total Tokens: [green]{self.tokens.total_tokens:,}[/green]")
            lines.append(f"  Input Tokens: [cyan]{self.tokens.input_tokens:,}[/cyan]")
            lines.append(f"  Output Tokens: [magenta]{self.tokens.output_tokens:,}[/magenta]")
            if self.tokens.cached_tokens > 0:
                cache_rate = (self.tokens.cached_tokens / self.tokens.input_tokens * 100) if self.tokens.input_tokens > 0 else 0
                lines.append(f"  Cached Tokens: [blue]{self.tokens.cached_tokens:,} ({cache_rate:.1f}%)[/blue]")
            if self.tokens.reasoning_tokens > 0:
                lines.append(f"  Reasoning Tokens: [dim]{self.tokens.reasoning_tokens:,}[/dim]")
            lines.append("")
        
        # Tool Stats
        if self.tools.total_calls > 0:
            lines.append("[bold green]🛠️ Tool Usage[/bold green]")
            lines.append(f"  Total Calls: [green]{self.tools.total_calls}[/green]")
            lines.append(f"  Success Rate: [yellow]{self.tools.success_rate:.1f}%[/yellow]")
            lines.append("")
            
            if self.tools.by_name:
                lines.append("  [dim]Tool Breakdown:[/dim]")
                for tool_name, stats in sorted(self.tools.by_name.items()):
                    success_rate = (stats['success'] / stats['calls'] * 100) if stats['calls'] > 0 else 0
                    lines.append(f"    [cyan]{tool_name}[/cyan]: {stats['calls']} calls, {success_rate:.1f}% success")
                lines.append("")
        
        # Model breakdown
        if self.models_used:
            lines.append("[bold blue]🤖 Model Usage[/bold blue]")
            for model, stats in self.models_used.items():
                lines.append(f"  [cyan]{model}[/cyan]:")
                lines.append(f"    Total: [green]{stats.total_tokens:,}[/green] tokens")
                lines.append(f"    Input: [yellow]{stats.input_tokens:,}[/yellow], Output: [magenta]{stats.output_tokens:,}[/magenta]")
                if stats.cached_tokens > 0:
                    lines.append(f"    Cached: [blue]{stats.cached_tokens:,}[/blue]")
            lines.append("")
        
        return "\n".join(lines)

    def get_agent_stats_summary(self) -> str:
        """Get formatted statistics summary by agent."""
        lines = []

        # Session info
        lines.append(f"[bold cyan]Session Duration:[/bold cyan] {self.session_duration}")
        lines.append(f"[bold cyan]Current Agent:[/bold cyan] {self.current_agent or 'None'}")
        lines.append("")

        if not self.agents:
            lines.append("[dim]No agent statistics available[/dim]")
            return "\n".join(lines)

        # Agent breakdown
        lines.append("[bold magenta]🤖 Agent Statistics[/bold magenta]")

        for agent_name, agent_stats in sorted(self.agents.items()):
            lines.append(f"\n[bold cyan]{agent_name}[/bold cyan]")
            lines.append(f"  Tasks: [green]{agent_stats.total_tasks}[/green]")
            lines.append(f"  First used: [dim]{agent_stats.first_used.strftime('%H:%M:%S')}[/dim]")
            lines.append(f"  Last used: [dim]{agent_stats.last_used.strftime('%H:%M:%S')}[/dim]")

            # API stats
            if agent_stats.api.total_requests > 0:
                lines.append(f"  API Requests: [green]{agent_stats.api.total_requests}[/green]")
                if agent_stats.api.total_errors > 0:
                    lines.append(f"  API Errors: [red]{agent_stats.api.total_errors}[/red] ({agent_stats.api.error_rate:.1f}%)")

            # Token stats
            if agent_stats.tokens.total_tokens > 0:
                lines.append(f"  Total Tokens: [yellow]{agent_stats.tokens.total_tokens:,}[/yellow]")
                lines.append(f"    Input: [cyan]{agent_stats.tokens.input_tokens:,}[/cyan], Output: [magenta]{agent_stats.tokens.output_tokens:,}[/magenta]")
                if agent_stats.tokens.cached_tokens > 0:
                    cache_rate = (agent_stats.tokens.cached_tokens / agent_stats.tokens.input_tokens * 100) if agent_stats.tokens.input_tokens > 0 else 0
                    lines.append(f"    Cached: [blue]{agent_stats.tokens.cached_tokens:,} ({cache_rate:.1f}%)[/blue]")

            # Tool stats
            if agent_stats.tools.total_calls > 0:
                lines.append(f"  Tool Calls: [green]{agent_stats.tools.total_calls}[/green] ({agent_stats.tools.success_rate:.1f}% success)")

                # Top 3 tools
                if agent_stats.tools.by_name:
                    top_tools = sorted(agent_stats.tools.by_name.items(), key=lambda x: x[1]['calls'], reverse=True)[:3]
                    tool_list = []
                    for tool_name, stats in top_tools:
                        tool_list.append(f"{tool_name}({stats['calls']})")
                    lines.append(f"    Top tools: [dim]{', '.join(tool_list)}[/dim]")

            # Model stats
            if agent_stats.models_used:
                model_list = []
                for model, stats in agent_stats.models_used.items():
                    model_list.append(f"{model}({stats.total_tokens:,})")
                lines.append(f"  Models: [dim]{', '.join(model_list)}[/dim]")

        return "\n".join(lines)


# Global session stats instance
session_stats = SessionStats()
