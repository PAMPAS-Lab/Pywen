from __future__ import annotations
import os
import re
import shlex
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Any, Optional
from .base_command import BaseCommand, CommandResult, CommandAction
from pywen.config.prompt_commands import PromptSpec, parse_prompt_args, expand_prompt_template

PROMPTS_CMD_PREFIX = "prompts"
PROMPT_ARG_REGEX = re.compile(r"\$[A-Z][A-Z0-9_]*")

@dataclass(frozen=True)
class CustomPrompt:
    name: str
    path: Path
    content: str
    description: Optional[str]
    argument_hint: Optional[str]

class PromptArgsError(Exception):
    def __init__(self, command: str, message: str) -> None:
        super().__init__(message)
        self.command = command
        self.message = message

class PromptExpansionError(Exception):
    def __init__(self, command: str, message: str) -> None:
        super().__init__(message)
        self.command = command
        self.message = message

def discover_prompts_in(directory: Path, exclude: Iterable[str] = ()) -> List[CustomPrompt]:
    exclude_set = set(exclude)
    if not directory.exists():
        return []
    prompts: List[CustomPrompt] = []
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() != ".md":
            continue
        name = entry.stem
        if name in exclude_set:
            continue
        try:
            content = entry.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        description, argument_hint, body = parse_frontmatter(content)
        prompts.append(
            CustomPrompt(
                name=name,
                path=entry,
                content=body,
                description=description,
                argument_hint=argument_hint,
            )
        )
    return sorted(prompts, key=lambda prompt: prompt.name)

def parse_frontmatter(content: str) -> Tuple[Optional[str], Optional[str], str]:
    segments = content.splitlines(keepends=True)
    if not segments:
        return None, None, ""
    first_line = segments[0].rstrip("\r\n")
    if first_line.strip() != "---":
        return None, None, content

    desc: Optional[str] = None
    hint: Optional[str] = None
    consumed = len(segments[0])
    frontmatter_closed = False

    for segment in segments[1:]:
        line = segment.rstrip("\r\n")
        trimmed = line.strip()

        if trimmed == "---":
            consumed += len(segment)
            frontmatter_closed = True
            break
        if not trimmed or trimmed.startswith("#"):
            consumed += len(segment)
            continue
        if ":" in trimmed:
            key, value = trimmed.split(":", 1)
            key = key.strip().lower()
            val = value.strip()
            if len(val) >= 2 and (
                (val.startswith('"') and val.endswith('"'))
                or (val.startswith("'") and val.endswith("'"))
            ):
                val = val[1:-1]
            if key == "description":
                desc = val
            elif key in {"argument-hint", "argument_hint"}:
                hint = val
        consumed += len(segment)

    if not frontmatter_closed:
        return None, None, content

    body = content[consumed:] if consumed < len(content) else ""
    return desc, hint, body

def parse_slash_name(line: str) -> Optional[Tuple[str, str]]:
    if not line.startswith("/"):
        return None
    stripped = line[1:]
    name_end = len(stripped)
    for idx, ch in enumerate(stripped):
        if ch.isspace():
            name_end = idx
            break
    name = stripped[:name_end]
    if not name:
        return None
    rest = stripped[name_end:].lstrip()
    return name, rest

def parse_positional_args(rest: str) -> List[str]:
    return list(shlex.split(rest))

def prompt_argument_names(content: str) -> List[str]:
    seen = set()
    names: List[str] = []
    for match in PROMPT_ARG_REGEX.finditer(content):
        if match.start() > 0 and content[match.start() - 1] == "$":
            continue
        name = content[match.start() + 1 : match.end()]
        if name == "ARGUMENTS":
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names

def parse_prompt_inputs(rest: str, command: str) -> Dict[str, str]:
    if not rest.strip():
        return {}
    parsed: Dict[str, str] = {}
    for token in shlex.split(rest):
        if "=" not in token:
            raise PromptArgsError(
                command=command,
                message=(
                    f"Could not parse {command}: expected key=value but found '{token}'. "
                    "Wrap values in double quotes if they contain spaces."
                ),
            )
        key, value = token.split("=", 1)
        if not key:
            raise PromptArgsError(
                command=command,
                message=f"Could not parse {command}: expected a name before '=' in '{token}'.",
            )
        parsed[key] = value
    return parsed

def expand_custom_prompt(
    text: str, custom_prompts: Sequence[CustomPrompt]
) -> Optional[str]:
    parsed = parse_slash_name(text)
    if not parsed:
        return None
    name, rest = parsed
    if not name.startswith(f"{PROMPTS_CMD_PREFIX}:"):
        return None
    prompt_name = name[len(f"{PROMPTS_CMD_PREFIX}:") :]
    prompt = next((item for item in custom_prompts if item.name == prompt_name), None)
    if not prompt:
        return None

    required = prompt_argument_names(prompt.content)
    if required:
        command = f"/{name}"
        try:
            inputs = parse_prompt_inputs(rest, command)
        except PromptArgsError as error:
            raise PromptExpansionError(command=command, message=error.message) from error
        missing = [key for key in required if key not in inputs]
        if missing:
            list_text = ", ".join(missing)
            raise PromptExpansionError(
                command=command,
                message=(
                    f"Missing required args for {command}: {list_text}. "
                    "Provide as key=value (quote values with spaces)."
                ),
            )

        def replace(match: re.Match[str]) -> str:
            start = match.start()
            if start > 0 and prompt.content[start - 1] == "$":
                return match.group(0)
            whole = match.group(0)
            key = whole[1:]
            return inputs.get(key, whole)

        return PROMPT_ARG_REGEX.sub(replace, prompt.content)

    pos_args = parse_positional_args(rest)
    return expand_numeric_placeholders(prompt.content, pos_args)

def prompt_has_numeric_placeholders(content: str) -> bool:
    if "$ARGUMENTS" in content:
        return True
    for i in range(len(content) - 1):
        if content[i] == "$" and content[i + 1].isdigit() and content[i + 1] != "0":
            return True
    return False

def expand_numeric_placeholders(content: str, args: Sequence[str]) -> str:
    out: List[str] = []
    i = 0
    cached_joined_args: Optional[str] = None
    while True:
        offset = content.find("$", i)
        if offset == -1:
            out.append(content[i:])
            break
        out.append(content[i:offset])
        rest = content[offset:]
        if len(rest) >= 2:
            second = rest[1]
            if second == "$":
                out.append("$$")
                i = offset + 2
                continue
            if "1" <= second <= "9":
                idx = ord(second) - ord("1")
                if idx < len(args):
                    out.append(args[idx])
                i = offset + 2
                continue
        if len(rest) > len("ARGUMENTS") and rest[1:].startswith("ARGUMENTS"):
            if args:
                if cached_joined_args is None:
                    cached_joined_args = " ".join(args)
                out.append(cached_joined_args)
            i = offset + 1 + len("ARGUMENTS")
            continue
        out.append("$")
        i = offset + 1
    return "".join(out)


def expand_if_numeric_with_positional_args(
    prompt: CustomPrompt, first_line: str
) -> Optional[str]:
    if prompt_argument_names(prompt.content):
        return None
    if not prompt_has_numeric_placeholders(prompt.content):
        return None
    args = extract_positional_args_for_prompt_line(first_line, prompt.name)
    if not args:
        return None
    return expand_numeric_placeholders(prompt.content, args)


def extract_positional_args_for_prompt_line(
    line: str, prompt_name: str
) -> List[str]:
    trimmed = line.lstrip()
    if not trimmed.startswith("/"):
        return []
    rest = trimmed[1:]
    if not rest.startswith(f"{PROMPTS_CMD_PREFIX}:"):
        return []
    after_prefix = rest[len(f"{PROMPTS_CMD_PREFIX}:") :]
    parts = after_prefix.split(None, 1)
    cmd = parts[0] if parts else ""
    if cmd != prompt_name:
        return []
    args_str = parts[1].strip() if len(parts) > 1 else ""
    if not args_str:
        return []
    return parse_positional_args(args_str)


class CustomCommand(BaseCommand):
    def __init__(self, spec: PromptSpec):
        # 命令名用 spec.name，用户输入 /review
        name = spec.name.lower()
        description = spec.description
        super().__init__(name=name, description=description, alt_name=None)
        self._spec = spec

    async def execute(self, context: Dict[str, Any], args: str) -> CommandResult:
        positional, named = parse_prompt_args(args)
        expanded = expand_prompt_template(self._spec.template, positional, named).strip()

        if not expanded:
            console = context.get("console")
            if console:
                console.print(f"Prompt '{self.name}' expanded to empty text.", "yellow")
            return CommandResult(action=CommandAction.HANDLED)

        # 把 expanded 作为改写后的用户输入，继续走 agent
        return CommandResult(action=CommandAction.REWRITE, text=expanded)


