from __future__ import annotations
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple 

@dataclass(frozen=True)
class PromptSpec:
    """
    一个自定义命令的规格。
    name: 文件名去扩展名 (e.g. review.md -> review)
    description: 展示给 /help 或 UI 的描述
    argument_hint: 参数提示（可选）
    template: Markdown 正文作为模板
    source_path: 文件路径
    """
    name: str
    description: str
    argument_hint: str
    template: str
    source_path: Path

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

def _split_front_matter(text: str) -> Tuple[Dict[str, str], str]:
    """
    极简 front matter 解析：
    - 若以 '---' 开头，并存在第二个 '---'，则中间为 meta，后面为 body。
    - meta 支持最常用的 key: value 行（不支持复杂 YAML 结构）。
    """
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}, text

    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, text

    header_lines = lines[1:end]
    body = "\n".join(lines[end + 1:])

    meta: Dict[str, str] = {}
    for ln in header_lines:
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body

def get_default_prompt_dirs(cwd: Path | None = None) -> List[Path]:
    """
    搜索顺序：
    1) 当前目录 ./.pywen/prompts
    2) 用户目录 ~/.pywen/prompts
    """
    base = cwd or Path.cwd()
    return [
        base / ".pywen" / "prompts",
        Path.home() / ".pywen" / "prompts",
    ]

def _load_prompt_specs_from_dir(prompts_dir: Path) -> List[PromptSpec]:
    """扫描单个目录顶层 *.md（不递归）"""
    if not prompts_dir.exists() or not prompts_dir.is_dir():
        return []

    specs: List[PromptSpec] = []
    for p in sorted(prompts_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() != ".md":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        meta, body = _split_front_matter(text)

        name = p.stem
        desc = meta.get("description", f"Custom prompt: {name}")
        hint = meta.get("argument-hint", meta.get("argument_hint", ""))

        specs.append(PromptSpec(
                name=name,
                description=desc,
                argument_hint=hint,
                template=body.strip(),
                source_path=p,
            )
        )
    return specs


def load_prompt_specs(prompt_dirs: List[Path] | None = None, *,
    cwd: Path | None = None,) -> List[PromptSpec]:
    """
    按优先级合并多个目录的 prompt：
    - 默认顺序：./.pywen/prompts -> ~/.pywen/prompts
    - 同名（stem 相同）时：先扫描到的优先
    """
    dirs = prompt_dirs or get_default_prompt_dirs(cwd=cwd)

    merged: Dict[str, PromptSpec] = {}
    for d in dirs:
        for spec in _load_prompt_specs_from_dir(d):
            key = spec.name.lower()
            if key not in merged:
                merged[key] = spec

    return [merged[k] for k in sorted(merged.keys())]

# 1) 用于模板替换的 token 匹配
_VAR_RE = re.compile(r"\$[A-Z][A-Z0-9_]*|\$ARGUMENTS|\$[1-9]|\$\$")

# 2) 用于 required-named-args 检测
#    注意：只把 $[A-Z][A-Z0-9_]* 视为“命名参数占位符”，并排除 ARGUMENTS
_PROMPT_NAMED_VAR_RE = re.compile(r"\$[A-Z][A-Z0-9_]*")

def parse_prompt_args(args: str) -> Tuple[List[str], Dict[str, str]]:
    """
    解析 args，支持：
    - 位置参数：/review a b c   -> $1=a, $2=b, $ARGUMENTS="a b c"
    - 命名参数：/review file=xx Focus="hello world" -> $FILE, $FOCUS
    """
    tokens = shlex.split(args) if args.strip() else []
    positional: List[str] = []
    named: Dict[str, str] = {}

    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            if _is_valid_named_key(k):
                named[k.upper()] = v
                continue
        positional.append(t)

    return positional, named


def required_named_args(template: str) -> List[str]:
    """
    从模板中提取“required named args”，迁移旧实现 prompt_argument_names 的思路：
    - 匹配 $FOO（FOO 为大写字母开头 + 大写/数字/下划线）
    - 排除 $ARGUMENTS
    - 跳过转义形式 $$FOO（前一个字符也是 $）
    - 去重并保持出现顺序
    """
    seen = set()
    out: List[str] = []

    for m in _PROMPT_NAMED_VAR_RE.finditer(template):
        start = m.start()
        if start > 0 and template[start - 1] == "$":
            continue

        var = m.group(0)[1:]
        if var == "ARGUMENTS":
            continue

        if var not in seen:
            seen.add(var)
            out.append(var)

    return out

def validate_required_named_args(*,template: str,named: Dict[str, str],command: str,) -> None:
    """
    若模板需要的 named args 未提供，则抛 PromptExpansionError。
    """
    required = required_named_args(template)
    if not required:
        return

    missing = [k for k in required if k not in named]
    if not missing:
        return

    list_text = ", ".join(missing)
    raise PromptExpansionError(
        command=command,
        message=(
            f"Missing required args for {command}: {list_text}. "
            "Provide as key=value (quote values with spaces)."
        ),
    )

def expand_prompt_template(template: str, positional: List[str], named: Dict[str, str]) -> str:
    """
    展开模板占位符：
    - $$ -> 字面量 $
    - $ARGUMENTS -> 所有位置参数拼接
    - $1..$9 -> 对应位置参数
    - $FOO -> named["FOO"]）
    """
    def repl(m: re.Match) -> str:
        tok = m.group(0)

        if tok == "$$":
            return "$"

        if tok == "$ARGUMENTS":
            return " ".join(positional)

        # $1..$9
        if len(tok) == 2 and tok[0] == "$" and tok[1].isdigit():
            idx = int(tok[1]) - 1
            return positional[idx] if 0 <= idx < len(positional) else ""

        # $FOO (FOO is uppercase)
        if tok.startswith("$") and tok[1:].isupper():
            return named.get(tok[1:], "")
        return tok

    return _VAR_RE.sub(repl, template)


def _is_valid_named_key(k: str) -> bool:
    """
    允许：
    - 首字符：字母（a-zA-Z）
    - 后续：字母/数字/下划线
    """
    if not k or not k[0].isalpha():
        return False
    for ch in k:
        if not (ch.isalpha() or ch.isdigit() or ch == "_"):
            return False
    return True
