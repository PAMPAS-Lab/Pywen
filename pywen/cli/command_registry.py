from __future__ import annotations
from typing import Dict, Iterable
from pywen.cli.commands.base_command import BaseCommand

class CommandRegistry:
    def __init__(self) -> None:
        self._commands: Dict[str, BaseCommand] = {}

    def register(self, cmd: BaseCommand) -> None:
        self._commands[cmd.name] = cmd
        if cmd.alt_name:
            self._commands[cmd.alt_name] = cmd

    def bulk_register(self, cmds: Iterable[BaseCommand]) -> None:
        for c in cmds:
            self.register(c)

    def get(self, name: str) -> BaseCommand | None:
        return self._commands.get(name)

    def all(self) -> Dict[str, BaseCommand]:
        return dict(self._commands)

