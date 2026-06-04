from __future__ import annotations
from types import SimpleNamespace
from pathlib import Path
import pytest
import textwrap
from pywen.config.manager import ConfigManager, ConfigError
from pywen.config.config import AppConfig

def create_config_file(tmp_path: Path, content: str) -> Path:
    """
    专门用于写入测试 YAML 文件。
    ConfigManager 会通过自身的方法从文件中读取配置。
    """
    cfg = tmp_path / "pywen_config.yaml"
    cfg.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return cfg

def test_resolve_without_args_uses_default_agent(tmp_path: Path):
    cfg_path = create_config_file(
        tmp_path,
        """
        default_agent: pywen
        agents:
          - agent_name: pywen
            provider: openai
            wire_api: chat
            model: pywen-model
            api_key: k1
            base_url: https://example.com/v1

          - agent_name: codex
            provider: openai
            wire_api: responses
            model: codex-model
            api_key: k2
            base_url: https://openai/v1

        runtime: {}
        """,
    )

    mgr = ConfigManager(config_path=cfg_path)
    app = mgr.resolve_effective_config() 

    assert isinstance(app, AppConfig)
    assert mgr.get_active_agent_name() == "pywen"
    assert mgr.get_active_model_name() == "pywen-model"

def test_list_agent_names(tmp_path: Path):
    cfg_path = create_config_file(
        tmp_path,
        """
        default_agent: codex
        agents:
          - agent_name: pywen
            provider: openai
            wire_api: chat
            model: A
            api_key: ak
            base_url: https://a

          - agent_name: codex
            provider: openai
            wire_api: responses
            model: B
            api_key: bk
            base_url: https://b
        """,
    )

    mgr = ConfigManager(config_path=cfg_path)
    mgr.resolve_effective_config()

    assert mgr.list_agent_names() == ["pywen", "codex"]


def test_switch_active_agent(tmp_path: Path):
    cfg_path = create_config_file(
        tmp_path,
        """
        default_agent: pywen
        agents:
          - agent_name: pywen
            provider: openai
            wire_api: chat
            model: M1
            api_key: k1
            base_url: https://x

          - agent_name: codex
            provider: openai
            wire_api: responses
            model: M2
            api_key: k2
            base_url: https://y
        runtime: {}
        """,
    )

    mgr = ConfigManager(config_path=cfg_path)
    mgr.resolve_effective_config()
    assert mgr.get_active_agent_name() == "pywen"

    mgr.switch_active_agent("codex")
    assert mgr.get_active_agent_name() == "codex"
    assert mgr.get_active_model_name() == "M2"

def test_cli_overrides_model_and_keys(tmp_path: Path):
    cfg_path = create_config_file(
        tmp_path,
        """
        default_agent: pywen
        agents:
          - agent_name: pywen
            provider: openai
            wire_api: chat
            model: base
            api_key: base_key
            base_url: https://base
            temperature: 0.1

        """,
    )

    args = SimpleNamespace(
        agent="pywen",
        model="cli-model",
        api_key="cli-key",
        base_url="https://cli/",
        temperature=0.8,
        max_tokens=2000,
        top_p=None,
        top_k=None,
        permission_mode=None,
    )

    mgr = ConfigManager(config_path=cfg_path)
    mgr.resolve_effective_config(args)
    ag = mgr.get_active_agent(args)

    assert ag.model.model_name == "cli-model"
    assert ag.model.api_key == "cli-key"
    assert ag.model.base_url == "https://cli"
    assert ag.model.temperature == 0.8
    assert ag.model.max_tokens == 2000


def test_env_overrides_when_yaml_missing(tmp_path: Path, monkeypatch):
    cfg_path = create_config_file(
        tmp_path,
        """
        default_agent: pywen
        agents:
          - agent_name: pywen
            provider: openai
            wire_api: chat
            model: ""
            api_key: ""
            base_url: ""
        runtime: {}
        """,
    )

    monkeypatch.setenv("PYWEN_MODEL", "env-model")
    monkeypatch.setenv("PYWEN_API_KEY", "env-key")
    monkeypatch.setenv("PYWEN_BASE_URL", "https://env")

    mgr = ConfigManager(config_path=cfg_path)
    mgr.resolve_effective_config()

    ag = mgr.get_active_agent()
    assert ag.model.model_name == "env-model"
    assert ag.model.api_key == "env-key"
    assert ag.model.base_url == "https://env"

def test_missing_required_fields_raise(tmp_path: Path):
    cfg_path = create_config_file(
        tmp_path,
        """
        default_agent: pywen
        agents:
          - agent_name: pywen
            provider: openai
            wire_api: chat
            model: ""
            api_key: ""
            base_url: ""
        """,
    )

    mgr = ConfigManager(config_path=cfg_path)
    with pytest.raises(SystemExit) as ei:
        mgr.resolve_effective_config()

    assert ei.value.code == 2


def test_args_none_works_everywhere(tmp_path: Path):
    cfg_path = create_config_file(
        tmp_path,
        """
        default_agent: codex
        agents:
          - agent_name: pywen
            provider: openai
            wire_api: chat
            model: A
            api_key: ak
            base_url: https://a
          - agent_name: codex
            provider: openai
            wire_api: responses
            model: B
            api_key: bk
            base_url: https://b
        runtime: {}
        """,
    )

    mgr = ConfigManager(config_path=cfg_path)

    app = mgr.resolve_effective_config()
    assert app.runtime["active_agent"] == "codex"

    assert mgr.get_active_agent_name() == "codex"
    assert mgr.get_active_model_name() == "B"

    assert mgr.list_agent_names() == ["pywen", "codex"]

    mgr.switch_active_agent("pywen")
    assert mgr.get_active_agent_name() == "pywen"
    assert mgr.get_active_model_name() == "A"
