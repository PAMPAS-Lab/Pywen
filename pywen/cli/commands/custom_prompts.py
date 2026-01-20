from __future__ import annotations
from typing import Dict, Any 
from .base_command import BaseCommand, CommandResult, CommandAction
from pywen.config.prompt_commands import PromptSpec, parse_prompt_args, expand_prompt_template, validate_required_named_args

class CustomCommand(BaseCommand):
    def __init__(self, spec: PromptSpec):
        name = spec.name.lower()
        description = spec.description
        super().__init__(name=name, description=description, alt_name=None)
        self._spec = spec

    async def execute(self, context: Dict[str, Any], args: str) -> CommandResult:
        positional, named = parse_prompt_args(args)
        validate_required_named_args(template=self._spec.template, named=named, command=f"/{self.name}")
        expanded = expand_prompt_template(self._spec.template, positional, named).strip()

        if not expanded:
            console = context.get("console")
            if console:
                console.print(f"Prompt '{self.name}' expanded to empty text.", "yellow")
            return CommandResult(action=CommandAction.HANDLED)

        # 把 expanded 作为改写后的用户输入，继续走 agent
        return CommandResult(action=CommandAction.REWRITE, text=expanded)
