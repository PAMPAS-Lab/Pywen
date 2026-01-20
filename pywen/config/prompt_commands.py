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
    body = "\n".join(lines[end + 1 :])

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
        text = p.read_text(encoding="utf-8")
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

def load_prompt_specs(prompt_dirs: List[Path] | None = None, *, cwd: Path | None = None,) -> List[PromptSpec]:
    """
    按优先级合并多个目录的 prompt：
    - 默认顺序：./.pywen/prompts -> ~/.pywen/prompts
    - 同名（stem 相同）时：先扫描到的优先（即本地覆盖全局）
    """
    dirs = prompt_dirs or get_default_prompt_dirs(cwd=cwd)

    merged: Dict[str, PromptSpec] = {}
    for d in dirs:
        for spec in _load_prompt_specs_from_dir(d):
            key = spec.name.lower()
            if key not in merged:
                merged[key] = spec

    return [merged[k] for k in sorted(merged.keys())]

_VAR_RE = re.compile(r"\$[A-Z][A-Z0-9_]*|\$ARGUMENTS|\$[1-9]|\$\$")

def parse_prompt_args(args: str) -> Tuple[List[str], Dict[str, str]]:
    """
    解析 args，支持：
    - 位置参数：/review a b c   -> $1=a, $2=b, $ARGUMENTS="a b c"
    - 命名参数：/review FILE=xx FOCUS="hello world" -> $FILE, $FOCUS
    规则：
    - KEY 必须是大写字母/数字/下划线（首字符字母）
    - 使用 shlex 支持引号与转义
    """
    tokens = shlex.split(args) if args.strip() else []
    positional: List[str] = []
    named: Dict[str, str] = {}

    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            if _is_valid_named_key(k):
                named[k] = v
                continue
        positional.append(t)

    return positional, named

def expand_prompt_template(template: str, positional: List[str], named: Dict[str, str]) -> str:
    """
    展开模板占位符：
    - $$ -> 字面量 $
    - $ARGUMENTS -> 所有位置参数拼接
    - $1..$9 -> 对应位置参数
    - $FOO -> named["FOO"]（未提供则为空串）
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
        # $FOO
        if tok.startswith("$") and tok[1:].isupper():
            return named.get(tok[1:], "")
        return tok

    return _VAR_RE.sub(repl, template)

def _is_valid_named_key(k: str) -> bool:
    if not k or not k[0].isalpha() or not k[0].isupper():
        return False
    for ch in k:
        if not (ch.isupper() or ch.isdigit() or ch == "_"):
            return False
    return True
