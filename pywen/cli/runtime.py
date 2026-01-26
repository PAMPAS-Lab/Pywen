from __future__ import annotations
import asyncio
import threading
from typing import Callable, Optional
from enum import Enum
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from pywen.agents.agent_events import Agent_Events
from pywen.agents.agent_manager import AgentManager
from pywen.cli.command_processor import CommandProcessor
from pywen.cli.cli_console import CLIConsole
from pywen.cli.commands.base_command import CommandAction, CommandResult
from pywen.config.manager import ConfigManager
from pywen.utils.key_binding import create_key_bindings
from pywen.llm.llm_basics import LLMMessage
from pywen.tools.tool_manager import ToolManager
from pywen.hooks.models import HookEvent
from pywen.utils.permission_manager import PermissionLevel, PermissionManager
from pywen.memory.memory_monitor import MemoryMonitor

class RunEndType(str, Enum):
    COMPLETED = "completed"
    TASK_COMPLETE = "task_complete"
    TURN_MAX_REACHED = "turn_max_reached"
    WAITING_FOR_USER = "waiting_for_user"
    CANCELLED = "cancelled"
    ERROR = "error"

class RunOutcome:
    def __init__(self, end: RunEndType, err: Exception | None = None) -> None:
        self.end = end
        self.err = err

class PromptDriver:
    def __init__(self, 
                 cli:CLIConsole, 
                 perm_mgr: PermissionManager, 
                 cancel_event_getter: Optional[Callable[[], Optional[CancellationToken]]] = None,
                 current_task_getter: Optional[Callable[[], Optional[asyncio.Task]]] = None,
                 exit_sentinel: str = "__PYWEN_QUIT__",
        ) -> None:
        self._cli:CLIConsole = cli
        self.exit_sentinel = exit_sentinel
        kbs = create_key_bindings(
            console_getter=lambda: cli,
            perm_mgr_getter=lambda: perm_mgr,
            cancel_event_getter= cancel_event_getter,
            current_task_getter=current_task_getter,
            exit_sentinel=exit_sentinel,
        )
        self._session = PromptSession(
            history=InMemoryHistory(),
            auto_suggest=AutoSuggestFromHistory(),
            key_bindings= kbs,
            multiline=True,
            wrap_lines=True,
        )

    async def read_line(self, prompt) -> str:
        return await self._session.prompt_async(prompt, multiline=False)

class CommandRouter:
    def __init__(self) -> None:
        self._impl = CommandProcessor()

    async def try_handle(self, raw: str, *, context: dict) -> CommandResult:
        return await self._impl.process_command(raw, context)

    @property
    def cmd_mgr(self):
        return self._impl

class CancellationToken:
    def __init__(self) -> None:
        self._flag = threading.Event()
        self.current_task: asyncio.Task | None = None

    def set(self) -> None:
        self._flag.set()
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()

    def clear(self) -> None:
        self._flag.clear()
        self.current_task = None

    @property
    def is_set(self) -> bool:
        return self._flag.is_set()

class EventPump:
    """把 agent 事件流 → CLI 渲染"""
    def __init__(self, cli : CLIConsole) -> None:
        self._cli = cli

    async def run(self, agent_run_aiter, cancel_token: CancellationToken) -> str:
        async for event in agent_run_aiter:
            if cancel_token.is_set:
                self._cli.print("\n⚠️ Operation cancelled by user", "yellow")
                return Agent_Events.CANCEL

            await self._cli.handle_events(event)

            if event.type in {
                Agent_Events.TASK_COMPLETE,
                Agent_Events.TURN_MAX_REACHED,
                Agent_Events.WAITING_FOR_USER,
            }:
                return event.type
        return RunEndType.COMPLETED

class TurnRunner:
    """ 单次Turn """
    def __init__(self, agent_mgr, hook_mgr, cli) -> None:
        self.agent_mgr = agent_mgr
        self.hook_mgr = hook_mgr
        self.cli = cli
        self._pump = EventPump(cli)

    async def run_once(self, *, user_input: str, session_id: str, cancel_token: CancellationToken) -> RunOutcome:
        try:
            # 前置 Hook
            ok, msg, _ = await self.hook_mgr.emit(
                HookEvent.UserPromptSubmit,
                base_payload={"session_id": session_id, "prompt": user_input},
            )
            if not ok:
                self.cli.print(f"⛔ {msg or 'Prompt blocked by hook'}", "yellow")
                return RunOutcome(RunEndType.ERROR)

            cancel_token.clear()
            events = self.agent_mgr.agent_run(user_input)
            task = asyncio.create_task(self._pump.run(events, cancel_token))
            cancel_token.current_task = task
            result = await task  # "completed" / "cancelled" / Agent_Events.* / "waiting_for_user"

            # 后置 Hook
            ok2, msg2, extra = await self.hook_mgr.emit(
                HookEvent.Stop,
                base_payload={"session_id": session_id, "prompt": user_input},
            )
            if msg2:
                self.cli.print(msg2, "yellow")
            if not ok2:
                self.cli.print(f"⛔ {msg2 or 'Prompt blocked by hook'}", "yellow")

            if extra.get("additionalContext") and self.agent_mgr.current:
                self.agent_mgr.current.conversation_history.append(
                    LLMMessage(role="user", content=extra["additionalContext"])
                )

            if result == Agent_Events.WAITING_FOR_USER:
                return RunOutcome(RunEndType.WAITING_FOR_USER)
            if result == Agent_Events.CANCEL:
                return RunOutcome(RunEndType.CANCELLED)
            if result == RunEndType.COMPLETED:
                return RunOutcome(RunEndType.COMPLETED)
            if result == Agent_Events.TURN_MAX_REACHED:
                return RunOutcome(RunEndType.TURN_MAX_REACHED)
            if result == Agent_Events.TASK_COMPLETE:
                return RunOutcome(RunEndType.TASK_COMPLETE)
            return RunOutcome(RunEndType.COMPLETED)

        except asyncio.CancelledError:
            self.cli.print("\n⚠️ Task was cancelled", "yellow")
            return RunOutcome(RunEndType.CANCELLED)
        except KeyboardInterrupt:
            self.cli.print("\n⚠️ Operation interrupted by user", "yellow")
            return RunOutcome(RunEndType.CANCELLED)
        except Exception as e:
            self.cli.print(f"\nError: {e}", "red")
            return RunOutcome(RunEndType.ERROR, e)

class HeadlessRunner:
    """ 非交互模式 """
    def __init__(self, *, agent_mgr, hook_mgr, cli, perm_mgr: PermissionManager) -> None:
        self.agent_mgr = agent_mgr
        self.hook_mgr = hook_mgr
        self.cli = cli
        self.perm_mgr = perm_mgr
        self._runner = TurnRunner(agent_mgr, hook_mgr, cli)

    async def run(self, *, prompt: str, session_id: str, set_yolo: bool = True) -> RunOutcome:
        if set_yolo:
            self.perm_mgr.set_permission_level(PermissionLevel.YOLO)
        cancle = CancellationToken()
        outcome = await self._runner.run_once(
            user_input=prompt, session_id=session_id, cancel_token=cancle
        )
        return outcome

class InteractiveSession:
    """ 交互模式 """
    def __init__(self, 
                 *, 
                 config_mgr: ConfigManager, 
                 agent_mgr: AgentManager, 
                 hook_mgr, cli:CLIConsole, 
                 perm_mgr: PermissionManager, 
                 tool_mgr: ToolManager,
                 session_id: str
                 ) -> None:
        self.agent_mgr = agent_mgr
        self.hook_mgr = hook_mgr
        self.cli = cli
        self.perm_mgr = perm_mgr
        self.session_id = session_id
        self.cancel_event = CancellationToken()
        self.config_mgr = config_mgr
        self.tool_mgr = tool_mgr

        self._prompt = PromptDriver(
                cli, 
                perm_mgr, 
                cancel_event_getter=lambda: self.cancel_event,
                current_task_getter=lambda: self.cancel_event.current_task,
            )

        self._router = CommandRouter()
        self._runner = TurnRunner(agent_mgr, hook_mgr, cli)
        self.mm = MemoryMonitor(config_mgr)

    async def run(self) -> None:
        self.cli.start_interactive_mode()
        sid = self.session_id
        turn :int= 0
        while True:
            perm_level = self.perm_mgr.get_permission_level()
            model_name = self.config_mgr.get_active_model_name() or "N/A"
            self.cli.show_status_bar(model_name = model_name,  permission_level= perm_level.value)
            try:
                line = await self._prompt.read_line(self.cli.prompt_prefix(sid))
            except EOFError:
                self.cli.print("Goodbye!", "yellow")
                break
            except KeyboardInterrupt:
                self.cli.print("\nUse Ctrl+C again to quit, or type 'exit'", "yellow")
                continue

            if not line or not line.strip():
                continue

            if line == self._prompt.exit_sentinel:
                self.cli.print("Goodbye!", "yellow")
                break

            low = line.strip().lower()
            if low in {"exit", "quit", "q"}:
                self.cli.print("Goodbye!", "yellow")
                break

            ctx = {
                "console": self.cli,
                "agent_mgr": self.agent_mgr,
                "config_mgr": self.config_mgr,
                "hook_mgr": self.hook_mgr,
                "tool_mgr": self.tool_mgr,
                "cmd_mgr": self._router.cmd_mgr,
            }
            cmd_res = await self._router.try_handle(line, context=ctx)
            if cmd_res.action == CommandAction.EXIT:
                break
            if cmd_res.action == CommandAction.HANDLED:
                continue
            if cmd_res.action == CommandAction.REWRITE:
                effective_input = cmd_res.text or ""
            else:
                effective_input = line  # FORWARD
            if not effective_input.strip():
                continue
            
            self.cancel_event.clear()
            outcome = await self._runner.run_once(
                user_input=effective_input, session_id=sid, cancel_token=self.cancel_event
            )

            if outcome.end in (RunEndType.COMPLETED, RunEndType.TASK_COMPLETE, RunEndType.TURN_MAX_REACHED):
                turn += 1
                await self.agent_mgr.agent_context_compact(self.mm, turn=turn)
                continue
            if outcome.end is RunEndType.WAITING_FOR_USER:
                continue
            if outcome.end in (RunEndType.CANCELLED, RunEndType.ERROR):
                continue
