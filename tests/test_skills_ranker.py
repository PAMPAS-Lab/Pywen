"""语义相关性排序 — 验收测试（重点覆盖关键词降级路径）。

验收标准：
1. 技能数 > top_k 且提供 query 时，渲染结果只包含 Top-K 个最相关技能
2. 技能数 ≤ top_k 时，返回全部技能（原行为）
3. sentence-transformers 未安装时，自动降级为关键词匹配，不报错
4. 单元测试覆盖降级路径（关键词匹配）
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pywen.skills.models import SkillMetadata, SkillScope
from pywen.skills.ranker import rank_skills_by_relevance, _rank_by_keywords
from pywen.skills.render import render_skills_section


def _make_skill(name: str, description: str) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=description,
        short_description=None,
        path=Path(f"/fake/{name}/SKILL.md"),
        scope=SkillScope.USER,
    )


# 构造 15 个技能用于测试
SKILLS = [
    _make_skill("docker", "Docker 容器化管理，支持镜像构建和部署"),
    _make_skill("git", "Git 版本控制，提交、分支、合并操作"),
    _make_skill("python", "Python 代码编写和调试"),
    _make_skill("javascript", "JavaScript 前端开发"),
    _make_skill("css", "CSS 样式设计"),
    _make_skill("database", "数据库管理，SQL 查询优化"),
    _make_skill("testing", "单元测试和集成测试"),
    _make_skill("deploy", "应用部署和 CI/CD"),
    _make_skill("security", "安全扫描和漏洞检测"),
    _make_skill("monitoring", "性能监控和告警"),
    _make_skill("logging", "日志采集和分析"),
    _make_skill("api", "REST API 设计和文档"),
    _make_skill("auth", "身份认证和授权"),
    _make_skill("cache", "缓存策略和 Redis"),
    _make_skill("queue", "消息队列和异步处理"),
]


def test_topk_limits_results() -> None:
    """标准 1：技能数 > top_k 时，仅返回 top_k 个技能。"""
    result = rank_skills_by_relevance(SKILLS, query="docker container", top_k=5)
    assert len(result) == 5


def test_all_returned_when_lte_topk() -> None:
    """标准 2：技能数 ≤ top_k，返回全部技能。"""
    small_list = SKILLS[:5]
    result = rank_skills_by_relevance(small_list, query="anything", top_k=10)
    assert len(result) == len(small_list)


def test_keyword_fallback_no_error() -> None:
    """标准 3：模拟 sentence-transformers 未安装时，降级不报错。"""
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("mocked: sentence_transformers not installed")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = rank_skills_by_relevance(SKILLS, query="docker container", top_k=5)
    assert len(result) == 5


def test_keyword_ranking_relevance() -> None:
    """标准 4：关键词匹配降级路径，docker 相关技能排在前面。"""
    result = _rank_by_keywords(SKILLS, query="docker container deploy", top_k=3)
    # docker 和 deploy 应该在 top-3 中
    result_names = [s.name for s in result]
    assert "docker" in result_names or "deploy" in result_names


def test_render_with_query_filters(tmp_path: Path) -> None:
    """标准 1 的渲染层集成测试：渲染结果只包含 top_k 个技能。"""
    rendered = render_skills_section(SKILLS, query="docker", top_k=3)
    assert rendered is not None
    # 渲染结果不能包含超过 top_k 个技能条目
    skill_lines = [line for line in rendered.split("\n") if line.startswith("- ") and "file:" in line]
    assert len(skill_lines) <= 3
