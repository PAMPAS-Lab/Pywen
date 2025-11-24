from __future__ import annotations
import os
import json
from dataclasses import dataclass 
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, override,Mapping 
from pywen.tools.base_tool import BaseTool, ToolRiskLevel
from pywen.utils.tool_basics import ToolResult
from pywen.core.tool_registry2 import register_tool

BEGIN_PATCH_MARKER = "*** Begin Patch"
END_PATCH_MARKER = "*** End Patch"
ADD_FILE_MARKER = "*** Add File: "
DELETE_FILE_MARKER = "*** Delete File: "
UPDATE_FILE_MARKER = "*** Update File: "
MOVE_TO_MARKER = "*** Move to: "
EOF_MARKER = "*** End of File"
CHANGE_CONTEXT_MARKER = "@@ "
EMPTY_CHANGE_CONTEXT_MARKER = "@@"

GRAMMAR_SCHEMA = {
"type": "grammar",
"syntax": "lark",
"definition": r"""
start: begin_patch hunk+ end_patch
begin_patch: "*** Begin Patch" LF
end_patch: "*** End Patch" LF?

hunk: add_hunk | delete_hunk | update_hunk
add_hunk: "*** Add File: " filename LF add_line+
delete_hunk: "*** Delete File: " filename LF
update_hunk: "*** Update File: " filename LF change_move? change?

filename: /(.+)/
add_line: "+" /(.*)/ LF -> line

change_move: "*** Move to: " filename LF
change: (change_context | change_line)+ eof_line?
change_context: ("@@" | "@@ " /(.+)/) LF
change_line: ("+" | "-" | " ") /(.*)/ LF
eof_line: "*** End of File" LF

%import common.LF
"""
        }

FUNCTION_SCHEMA = {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "The entire contents of the apply_patch command"
                        },
                    },
                "required": ["input"],
                "additionalProperties": False
                }


FUNCTION_DESCRIPTION = r"""
Use the `apply_patch` tool to edit files.
Your patch language is a stripped‑down, file‑oriented diff format designed to be easy to parse and safe to apply. You can think of it as a high‑level envelope:

*** Begin Patch
[ one or more file sections ]
*** End Patch

Within that envelope, you get a sequence of file operations.
You MUST include a header to specify the action you are taking.
Each operation starts with one of three headers:

*** Add File: <path> - create a new file. Every following line is a + line (the initial contents).
*** Delete File: <path> - remove an existing file. Nothing follows.
*** Update File: <path> - patch an existing file in place (optionally with a rename).

May be immediately followed by *** Move to: <new path> if you want to rename the file.
Then one or more “hunks”, each introduced by @@ (optionally followed by a hunk header).
Within a hunk each line starts with:

For instructions on [context_before] and [context_after]:
- By default, show 3 lines of code immediately above and 3 lines immediately below each change. If a change is within 3 lines of a previous change, do NOT duplicate the first change’s [context_after] lines in the second change’s [context_before] lines.
- If 3 lines of context is insufficient to uniquely identify the snippet of code within the file, use the @@ operator to indicate the class or function to which the snippet belongs. For instance, we might have:
@@ class BaseClass
[3 lines of pre-context]
- [old_code]
+ [new_code]
[3 lines of post-context]

- If a code block is repeated so many times in a class or function such that even a single `@@` statement and 3 lines of context cannot uniquely identify the snippet of code, you can use multiple `@@` statements to jump to the right context. For instance:

@@ class BaseClass
@@ 	 def method():
[3 lines of pre-context]
- [old_code]
+ [new_code]
[3 lines of post-context]

The full grammar definition is below:
Patch := Begin { FileOp } End
Begin := "*** Begin Patch" NEWLINE
End := "*** End Patch" NEWLINE
FileOp := AddFile | DeleteFile | UpdateFile
AddFile := "*** Add File: " path NEWLINE { "+" line NEWLINE }
DeleteFile := "*** Delete File: " path NEWLINE
UpdateFile := "*** Update File: " path NEWLINE [ MoveTo ] { Hunk }
MoveTo := "*** Move to: " newPath NEWLINE
Hunk := "@@" [ header ] NEWLINE { HunkLine } [ "*** End of File" NEWLINE ]
HunkLine := (" " | "-" | "+") text NEWLINE

A full patch can combine several operations:

*** Begin Patch
*** Add File: hello.txt
+Hello world
*** Update File: src/app.py
*** Move to: src/main.py
@@ def greet():
-print("Hi")
+print("Hello, world!")
*** Delete File: obsolete.txt
*** End Patch

It is important to remember:

- You must include a header with your intended action (Add/Delete/Update)
- You must prefix new lines with `+` even when creating a new file
- File references can only be relative, NEVER ABSOLUTE.
"""

CUSTOM_DESCRIPTION = "Use the `apply_patch` tool to edit files. This is a FREEFORM tool, so do not wrap the patch in JSON."


class ParseError(Exception):
    pass

class InvalidPatchError(ParseError):
    def __init__(self, message: str):
        super().__init__(f"invalid patch: {message}")

class InvalidHunkError(ParseError):
    def __init__(self, message: str, line_number: int):
        super().__init__(f"invalid hunk at line {line_number}, {message}")
        self.line_number = line_number

@dataclass
class UpdateFileChunk:
    change_context: Optional[str]
    old_lines: List[str]
    new_lines: List[str]
    is_end_of_file: bool

class Hunk:
    def resolve_path(self, cwd: Path) -> Path:
        raise NotImplementedError

@dataclass
class AddFile(Hunk):
    path: Path
    contents: str
    def resolve_path(self, cwd: Path) -> Path:
        return cwd / self.path

@dataclass
class DeleteFile(Hunk):
    path: Path
    def resolve_path(self, cwd: Path) -> Path:
        return cwd / self.path

@dataclass
class UpdateFile(Hunk):
    path: Path
    move_path: Optional[Path]
    chunks: List[UpdateFileChunk]

    def resolve_path(self, cwd: Path) -> Path:
        return cwd / self.path

@dataclass
class ApplyPatchArgs:
    hunks: List[Hunk]
    patch: str
    workdir: Optional[str]

def parse_patch(patch: str, allow_heredoc: bool = False) -> ApplyPatchArgs:
    lines = [ln for ln in patch.strip().splitlines()]

    try:
        _check_patch_boundaries_strict(lines)
        boundary_checked: List[str] = lines
    except ParseError as e:
        if not allow_heredoc:
            raise
        inner = _check_patch_boundaries_lenient(lines, e)
        boundary_checked = list(inner)

    last_line_index = max(len(boundary_checked) - 1, 0)
    remaining = boundary_checked[1:last_line_index]

    hunks: List[Hunk] = []
    line_number = 2

    while remaining:
        hunk, consumed = _parse_one_hunk(remaining, line_number)
        hunks.append(hunk)
        line_number += consumed
        remaining = remaining[consumed:]

    patch_text = "\n".join(boundary_checked)
    return ApplyPatchArgs(hunks=hunks, patch=patch_text, workdir=None)

def _check_patch_boundaries_strict(lines: List[str]) -> None:
    if not lines:
        first_line = last_line = None
    elif len(lines) == 1:
        first_line = last_line = lines[0]
    else:
        first_line, last_line = lines[0], lines[-1]
    _check_start_and_end_lines_strict(first_line, last_line)

def _check_patch_boundaries_lenient(original_lines: List[str], original_error: ParseError) -> List[str]:
    if not original_lines:
        raise original_error
    first, last = original_lines[0], original_lines[-1]
    if first in ("<<EOF", "<<'EOF'", "<<\"EOF\"") and last.rstrip().endswith("EOF") and len(original_lines) >= 4:
        inner_lines = original_lines[1:-1]
        _check_patch_boundaries_strict(inner_lines)
        return inner_lines
    raise original_error

def _check_start_and_end_lines_strict(first_line: Optional[str], last_line: Optional[str]) -> None:
    if first_line is not None and last_line is not None and first_line == BEGIN_PATCH_MARKER and last_line == END_PATCH_MARKER:
        return
    if first_line is not None and first_line != BEGIN_PATCH_MARKER:
        raise InvalidPatchError("The first line of the patch must be '*** Begin Patch'")
    raise InvalidPatchError("The last line of the patch must be '*** End Patch'")

def _parse_one_hunk(lines: List[str], line_number: int) -> Tuple[Hunk, int]:
    first_line = lines[0].strip()

    # Add
    if first_line.startswith(ADD_FILE_MARKER):
        path = first_line[len(ADD_FILE_MARKER):]
        contents_parts: List[str] = []
        parsed_lines = 1
        for add_line in lines[1:]:
            if add_line.startswith('+'):
                contents_parts.append(add_line[1:] + "\n")
                parsed_lines += 1
            else:
                break
        contents = "".join(contents_parts)
        return AddFile(path=Path(path), contents=contents), parsed_lines

    # Delete
    if first_line.startswith(DELETE_FILE_MARKER):
        path = first_line[len(DELETE_FILE_MARKER):]
        return DeleteFile(path=Path(path)), 1

    # Update
    if first_line.startswith(UPDATE_FILE_MARKER):
        path = first_line[len(UPDATE_FILE_MARKER):]
        remaining = lines[1:]
        parsed_lines = 1

        # Optional: Move to
        move_path: Optional[Path] = None
        if remaining and remaining[0].startswith(MOVE_TO_MARKER):
            move_path = Path(remaining[0][len(MOVE_TO_MARKER):])
            remaining = remaining[1:]
            parsed_lines += 1

        chunks: List[UpdateFileChunk] = []
        while remaining:
            if remaining[0].strip() == "":
                parsed_lines += 1
                remaining = remaining[1:]
                continue
            if remaining[0].startswith("***"):
                break

            chunk, chunk_lines = _parse_update_file_chunk(
                remaining, line_number + parsed_lines, allow_missing_context=(len(chunks) == 0)
            )
            chunks.append(chunk)
            parsed_lines += chunk_lines
            remaining = remaining[chunk_lines:]

        if not chunks:
            raise InvalidHunkError(f"Update file hunk for path '{path}' is empty", line_number)

        return UpdateFile(path=Path(path), move_path=move_path, chunks=chunks), parsed_lines

    raise InvalidHunkError(
        f"'{first_line}' is not a valid hunk header. Valid hunk headers: '*** Add File: {{path}}', '*** Delete File: {{path}}', '*** Update File: {{path}}'",
        line_number,
    )

def _parse_update_file_chunk(lines: List[str], line_number: int, allow_missing_context: bool) -> Tuple[UpdateFileChunk, int]:
    if not lines:
        raise InvalidHunkError("Update hunk does not contain any lines", line_number)

    # @@ 处理
    if lines[0] == EMPTY_CHANGE_CONTEXT_MARKER:
        change_context, start_index = None, 1
    elif lines[0].startswith(CHANGE_CONTEXT_MARKER):
        change_context, start_index = lines[0][len(CHANGE_CONTEXT_MARKER):], 1
    else:
        if not allow_missing_context:
            raise InvalidHunkError(
                f"Expected update hunk to start with a @@ context marker, got: '{lines[0]}'",
                line_number,
            )
        change_context, start_index = None, 0

    if start_index >= len(lines):
        raise InvalidHunkError("Update hunk does not contain any lines", line_number + 1)

    chunk = UpdateFileChunk(change_context=change_context, old_lines=[], new_lines=[], is_end_of_file=False)
    parsed_lines = 0

    for line in lines[start_index:]:
        if line == EOF_MARKER:
            if parsed_lines == 0:
                raise InvalidHunkError("Update hunk does not contain any lines", line_number + 1)
            chunk.is_end_of_file = True
            parsed_lines += 1
            break

        if line == "":
            chunk.old_lines.append("")
            chunk.new_lines.append("")
        else:
            first = line[0]
            if first == ' ':
                chunk.old_lines.append(line[1:])
                chunk.new_lines.append(line[1:])
            elif first == '+':
                chunk.new_lines.append(line[1:])
            elif first == '-':
                chunk.old_lines.append(line[1:])
            else:
                if parsed_lines == 0:
                    raise InvalidHunkError(
                        f"Unexpected line found in update hunk: '{line}'. Every line should start with ' ' (context line), '+' (added line), or '-' (removed line)",
                        line_number + 1,
                    )
                break
        parsed_lines += 1

    return chunk, parsed_lines + start_index

def _normalise_unicode(s: str) -> str:
    mapping = {
        # dashes
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
        "\u2212": "-",
        # single quotes
        "\u2018": "'", "\u2019": "'", "\u201A": "'", "\u201B": "'",
        # double quotes
        "\u201C": '"', "\u201D": '"', "\u201E": '"', "\u201F": '"',
        # spaces
        "\u00A0": " ", "\u2002": " ", "\u2003": " ", "\u2004": " ", "\u2005": " ", "\u2006": " ",
        "\u2007": " ", "\u2008": " ", "\u2009": " ", "\u200A": " ", "\u202F": " ", "\u205F": " ",
        "\u3000": " ",
    }
    return "".join(mapping.get(ch, ch) for ch in s).strip()

def seek_sequence(lines: List[str], pattern: List[str], start: int, eof: bool) -> Optional[int]:
    if not pattern:
        return start
    if len(pattern) > len(lines):
        return None

    search_start = len(lines) - len(pattern) if eof and len(lines) >= len(pattern) else start
    last = len(lines) - len(pattern)
    if search_start < 0:
        search_start = 0
    if last < 0:
        return None
    for i in range(search_start, last + 1):
        if lines[i:i + len(pattern)] == pattern:
            return i
    for i in range(search_start, last + 1):
        ok = True
        for p_idx, pat in enumerate(pattern):
            if lines[i + p_idx].rstrip() != pat.rstrip():
                ok = False
                break
        if ok:
            return i
    for i in range(search_start, last + 1):
        ok = True
        for p_idx, pat in enumerate(pattern):
            if lines[i + p_idx].strip() != pat.strip():
                ok = False
                break
        if ok:
            return i
    for i in range(search_start, last + 1):
        ok = True
        for p_idx, pat in enumerate(pattern):
            if _normalise_unicode(lines[i + p_idx]) != _normalise_unicode(pat):
                ok = False
                break
        if ok:
            return i
    return None

class ApplyError(Exception):
    pass

def _compute_replacements(
    original_lines: List[str],
    file_path: Path,
    chunks: List[UpdateFileChunk],
) -> List[Tuple[int, int, List[str]]]:
    replacements: List[Tuple[int, int, List[str]]] = []
    line_index = 0

    for chunk in chunks:
        if chunk.change_context:
            idx = seek_sequence(original_lines, [chunk.change_context], line_index, eof=False)
            if idx is None:
                raise ApplyError(f"Failed to find context '{chunk.change_context}' in {file_path}")
            line_index = idx + 1

        pattern = chunk.old_lines
        new_slice = chunk.new_lines

        found = seek_sequence(original_lines, pattern, line_index, eof=chunk.is_end_of_file)

        if found is None and pattern and pattern[-1] == "":
            trimmed_pattern = pattern[:-1]
            trimmed_new = new_slice[:-1] if new_slice and new_slice[-1] == "" else new_slice
            found = seek_sequence(original_lines, trimmed_pattern, line_index, eof=chunk.is_end_of_file)
            if found is not None:
                pattern = trimmed_pattern
                new_slice = trimmed_new

        if found is None:
            preview = "\n".join(chunk.old_lines)
            raise ApplyError(f"Failed to locate expected lines in {file_path}:\n{preview}")

        start_idx = found
        replacements.append((start_idx, len(pattern), list(new_slice)))
        line_index = start_idx + len(pattern)

    replacements.sort(key=lambda t: t[0])
    return replacements

def _apply_replacements(original_lines: List[str], reps: List[Tuple[int, int, List[str]]]) -> List[str]:
    out: List[str] = []
    cursor = 0
    for start_idx, old_len, new_lines in reps:
        if start_idx < cursor:
            start_idx = cursor  # best effort 避免重叠
        out.extend(original_lines[cursor:start_idx])
        out.extend(new_lines)
        cursor = start_idx + old_len
    out.extend(original_lines[cursor:])
    return out

@register_tool(name = "apply_patch", providers=["codex"])
class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    display_name="Apply Patch"
    description= CUSTOM_DESCRIPTION
    parameter_schema= GRAMMAR_SCHEMA
    can_update_output=False
    risk_level=ToolRiskLevel.MEDIUM

    def get_risk_level(self, **kwargs) -> ToolRiskLevel:
        if kwargs.get("dry_run", False):
            return ToolRiskLevel.SAFE
        return ToolRiskLevel.MEDIUM

    @override
    async def _generate_confirmation_message(self, **kwargs) -> str:
        dry = kwargs.get("dry_run", False)
        mode = "dry-run" if dry else "apply"
        wd = kwargs.get("workdir") or os.getcwd()
        return f"[{mode}] Apply patch to workspace: {wd}"

    async def execute(self, **kwargs) -> ToolResult:
        patch_text : str = kwargs.get("input")  or ""
        workdir = Path(kwargs.get("workdir") or os.getcwd()).resolve()
        allow_heredoc = bool(kwargs.get("allow_heredoc", False))
        dry_run = bool(kwargs.get("dry_run", False))
        try:
            args = parse_patch(patch_text, allow_heredoc=allow_heredoc)
            if args.workdir:
                workdir = Path(args.workdir).expanduser().resolve()

            summary: Dict[str, Any] = {"dry_run": dry_run, "cwd": str(workdir), "changes": {}}
            for hunk in args.hunks:
                path = hunk.resolve_path(workdir).resolve()
                try:
                    path.relative_to(workdir)
                except Exception:
                    raise ApplyError(f"Refusing to write outside workspace: {path} (cwd={workdir})")

                if isinstance(hunk, AddFile):
                    detail = {"kind": "Add", "bytes": len(hunk.contents.encode("utf-8"))}
                    summary["changes"][str(path)] = detail
                    if not dry_run:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(hunk.contents, encoding="utf-8")

                elif isinstance(hunk, DeleteFile):
                    detail = {"kind": "Delete", "exists": path.exists()}
                    summary["changes"][str(path)] = detail
                    if not dry_run and path.exists():
                        path.unlink()

                elif isinstance(hunk, UpdateFile):
                    if not path.exists():
                        raise ApplyError(f"File to update not found: {path}")
                    original = path.read_text(encoding="utf-8")
                    original_lines = original.split("\n")
                    if original_lines and original_lines[-1] == "":
                        original_lines = original_lines[:-1]

                    reps = _compute_replacements(original_lines, path, hunk.chunks)
                    new_lines = _apply_replacements(original_lines, reps)
                    new_content = "\n".join(new_lines) + "\n"

                    detail = {
                        "kind": "Update",
                        "replacements": [{"start": s, "old_len": l, "new_len": len(n)} for (s, l, n) in reps],
                        "moved_to": str((workdir / hunk.move_path).resolve()) if hunk.move_path else None,
                        "size_bytes": len(new_content.encode("utf-8")),
                    }
                    summary["changes"][str(path)] = detail

                    if not dry_run:
                        path.write_text(new_content, encoding="utf-8")
                        if hunk.move_path:
                            target = (workdir / hunk.move_path).resolve()
                            target.parent.mkdir(parents=True, exist_ok=True)
                            path.rename(target)
                else:
                    raise ApplyError(f"Unknown hunk variant: {hunk}")

            kinds = [v.get("kind") for v in summary["changes"].values()]
            add_n = sum(1 for k in kinds if k == "Add")
            del_n = sum(1 for k in kinds if k == "Delete")
            upd_n = sum(1 for k in kinds if k == "Update")
            short = f"Applied patch (add={add_n}, delete={del_n}, update={upd_n}, dry_run={dry_run})"

            return ToolResult(call_id= "", result=json.dumps(summary, ensure_ascii=False),
                error=None, display=None, metadata=summary, summary=short,)

        except (InvalidPatchError, InvalidHunkError, ApplyError, ParseError) as e:
            return ToolResult(call_id= "", result=None, error=str(e), display=None,
                metadata={"dry_run": dry_run, "cwd": str(workdir), "allow_heredoc": allow_heredoc,},
                summary="apply_patch failed",
            )
        except Exception as e:
            return ToolResult(call_id= "", result=None, error=f"Unexpected error: {e}", display=None, 
                    metadata={ "dry_run": dry_run, "cwd": str(workdir), "allow_heredoc": allow_heredoc,},
                    summary="apply_patch crashed",
            )

    def build(self, provider:str = "", func_type : str = "") -> Mapping[str, Any]:
        """ codex专用 """
        if func_type == "" or func_type.lower() == "custom"  or func_type.lower() == "freeform":
            return {
                    "type" : "custom",
                    "name" : self.name,
                    "description": self.description,
                    "format": self.parameter_schema,
                    }
        return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameter_schema
                },
            }
