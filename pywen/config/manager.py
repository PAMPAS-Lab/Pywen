from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
import yaml
from .config import AppConfig

PLACEHOLDERS = {
    "your-qwen-api-key-here",
    "changeme",
    "placeholder",
    "YOUR_API_KEY_HERE",
}

ENV_PREFIX = "PYWEN"

class ConfigError(RuntimeError):
    """配置相关错误。"""

class ConfigManager:
    def __init__(self, config_path: Optional[str | Path] = None) -> None:
        self.config_path: Path = (
            Path(config_path) if config_path else self.get_default_config_path()
        )
        self._raw_config: Optional[Dict[str, Any]] = None
        self._app_config: Optional[AppConfig] = None

    @staticmethod
    def get_pywen_config_dir() -> Path:
        d = Path.home() / ".pywen"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def get_default_config_path(cls) -> Path:
        return cls.get_pywen_config_dir() / "pywen_config.yaml"

    @staticmethod
    def get_default_hooks_path() -> Path:
        return ConfigManager.get_pywen_config_dir() / "pywen_hooks.yaml"

    @staticmethod
    def get_trajectories_dir() -> Path:
        d = ConfigManager.get_pywen_config_dir() / "trajectories"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_raw(self) -> Dict[str, Any]:
        """只读 YAML，返回原始 dict（不含 CLI/ENV 中的信息）。"""
        path = self._resolve_config_path()
        data = self._read_yaml(path)
        if not isinstance(data, dict):
            raise ConfigError(f"Config file must be a mapping (YAML dict): {path}")
        self._raw_config = data
        return data

    def get_raw_config(self) -> Dict[str, Any]:
        if self._raw_config is None:
            return self.load_raw()
        return self._raw_config

    def save_raw(self, cfg: Mapping[str, Any]) -> Path:
        path = self.config_path
        self._write_yaml(path, cfg)
        self._raw_config = dict(cfg)
        self._app_config = None
        return path

    def save_raw_as(self, cfg: Mapping[str, Any], target_path: str | Path) -> Path:
        target = Path(target_path)
        self._write_yaml(target, cfg)
        self._raw_config = dict(cfg)
        self._app_config = None
        return target

    @classmethod
    def find_config_file(cls, filename: str = "pywen_config.yaml") -> Optional[Path]:
        candidates = [cls.get_default_config_path(), Path.cwd() / filename]
        for parent in Path.cwd().parents:
            candidates.append(parent / filename)
        for p in candidates:
            if p.exists():
                return p
        return None

    def default_config_exists(self) -> bool:
        return self.get_default_config_path().exists()

    def resolve_effective_config(self, args: Any) -> AppConfig:
        """ 考虑CLI参数，环境变量后的“最终有效配置” """
        raw = self.get_raw_config()

        models_list = raw.get("models", [])
        models_by_name = self._index_models(models_list)

        active_name = self._select_active_agent_name(raw, models_by_name, args)
        active_agent_cfg = models_by_name[active_name]

        self._apply_field_priority(active_agent_cfg, active_name, args)

        missing = self._find_missing_required_fields(active_agent_cfg)
        if missing:
            raise ConfigError(
                f"Missing required fields in agent '{active_name}': {missing}. "
                "Please update your YAML config or environment variables."
            )

        runtime = raw.setdefault("runtime", {})
        runtime["active_agent"] = active_name

        cli_perm = getattr(args, "permission_mode", None)
        if isinstance(cli_perm, str) and cli_perm.strip():
            raw["permission_level"] = cli_perm.strip()

        app_cfg = AppConfig.model_validate(raw)
        self._app_config = app_cfg
        return app_cfg

    def get_app_config(self, args: Any) -> AppConfig:
        """获取最终的 AppConfig 对象（带缓存）。"""
        if self._app_config is None:
            return self.resolve_effective_config(args)
        return self._app_config

    def switch_active_agent(self, agent_name: str, args: Any) -> AppConfig:
        """
        运行中切换当前使用的 agent。
        - 会重新按优先级应用 CLI / ENV / YAML 到该 agent
        - 会更新 raw['runtime']['active_agent']
        - 会重新生成 AppConfig 并缓存
        """
        raw = self.get_raw_config()
        models_by_name = self._index_models(raw.get("models", []))

        name = agent_name.strip()
        if name.lower().endswith("agent"):
            name = name[: -len("agent")]
        if name not in models_by_name:
            raise ConfigError(f"Agent '{name}' is not defined in 'models'.")

        agent_cfg = models_by_name[name]
        self._apply_field_priority(agent_cfg, name, args)

        missing = self._find_missing_required_fields(agent_cfg)
        if missing:
            raise ConfigError(
                f"Missing required fields in agent '{name}': {missing}. "
                "Please update your YAML config or environment variables."
            )

        runtime = raw.setdefault("runtime", {})
        runtime["active_agent"] = name

        cli_perm = getattr(args, "permission_mode", None)
        if isinstance(cli_perm, str) and cli_perm.strip():
            raw["permission_level"] = cli_perm.strip()

        app_cfg = AppConfig.model_validate(raw)
        self._app_config = app_cfg
        return app_cfg

    def get_active_agent_name(self, args: Any) -> str:
        """辅助方法：返回当前激活的 agent 名称。"""
        cfg = self.get_app_config(args)
        return cfg.active_agent_name

    def get_active_model(self, args: Any):
        """辅助方法：返回当前激活的 ModelConfig。"""
        cfg = self.get_app_config(args)
        return cfg.active_model

    @staticmethod
    def _index_models(models: Any) -> Dict[str, Dict[str, Any]]:
        """
        将 YAML 中的 models 列表转为 agent_name -> dict 的索引。
        现在 schema 统一，要求每个 item 都必须有非空的 agent_name。
        """
        if not isinstance(models, list):
            raise ConfigError("Config field 'models' must be a list.")

        indexed: Dict[str, Dict[str, Any]] = {}
        for item in models:
            if not isinstance(item, dict):
                raise ConfigError("Each item in 'models' must be a mapping.")

            name = item.get("agent_name")
            if not isinstance(name, str) or not name.strip():
                raise ConfigError("Each agent must have a non-empty 'agent_name'.")

            key = name.strip()
            if key in indexed:
                raise ConfigError(f"Duplicate agent_name: {key}")
            indexed[key] = item

        if not indexed:
            raise ConfigError("'models' list is empty.")
        return indexed

    def _select_active_agent_name(
        self,
        raw_cfg: Mapping[str, Any],
        models_by_name: Mapping[str, Dict[str, Any]],
        args: Any,
    ) -> str:
        """
        选择当前 active agent 名称：
        CLI --agent > default_agent > 唯一的一个 agent
        """
        cli_agent = getattr(args, "agent", None)
        if isinstance(cli_agent, str) and cli_agent.strip():
            name = cli_agent.strip()
            if name not in models_by_name:
                raise ConfigError(
                    f"CLI requested agent '{name}', but it's not found in 'models'."
                )
            return name

        default_agent = raw_cfg.get("default_agent")
        if isinstance(default_agent, str) and default_agent.strip():
            name = default_agent.strip()
            if name not in models_by_name:
                raise ConfigError(
                    f"default_agent '{name}' is not defined in 'models'."
                )
            return name

        if len(models_by_name) == 1:
            return next(iter(models_by_name.keys()))

        raise ConfigError(
            "No agent selected and 'default_agent' is not set, "
            "while multiple models are configured. "
            "Please set 'default_agent' or use --agent."
        )

    def _apply_field_priority(
        self,
        agent_cfg: Dict[str, Any],
        agent_name: str,
        args: Any,
    ) -> None:
        """
        对单个 agent 的配置按优先级进行覆盖：
        1. CLI 参数
        2. YAML 原有值
        3. 环境变量（仅 api_key/base_url/model）
        """
        cli_fields = ("api_key", "base_url", "model", "temperature", "max_tokens")

        for field in cli_fields:
            cli_value = getattr(args, field, None)
            if cli_value is not None:
                agent_cfg[field] = self._normalize_field(field, cli_value)
                continue

            current = agent_cfg.get(field)
            if not self._is_missing(current):
                agent_cfg[field] = self._normalize_field(field, current)
                continue

            if field in ("api_key", "base_url", "model"):
                env_val = self._get_env_for_field(field, agent_name)
                if env_val is not None:
                    agent_cfg[field] = self._normalize_field(field, env_val)

    @staticmethod
    def _normalize_field(field: str, value: Any) -> Any:
        if value is None:
            return None
        if field == "base_url":
            return str(value).strip().rstrip("/")
        if field in ("api_key", "model"):
            return str(value).strip()
        return value

    @staticmethod
    def _is_missing(val: Any) -> bool:
        if val is None:
            return True
        s = str(val).strip()
        if not s:
            return True
        return s.lower() in PLACEHOLDERS

    def _get_env_for_field(self, field: str, agent_name: str) -> Optional[str]:
        key_suffix = {
            "api_key": "API_KEY",
            "base_url": "BASE_URL",
            "model": "MODEL",
        }.get(field)
        if key_suffix is None:
            return None

        name_up = agent_name.upper()
        candidates = [
            f"{ENV_PREFIX}_{name_up}_{key_suffix}",
            f"{ENV_PREFIX}_{key_suffix}",
            key_suffix,
        ]
        for k in candidates:
            v = os.getenv(k)
            if v and str(v).strip():
                return str(v).strip()
        return None

    @staticmethod
    def _find_missing_required_fields(agent_cfg: Mapping[str, Any]) -> List[str]:
        missing: List[str] = []
        for field in ("api_key", "base_url", "model"):
            if ConfigManager._is_missing(agent_cfg.get(field)):
                missing.append(field)
        return missing

    def _resolve_config_path(self) -> Path:
        if self.config_path and self.config_path.exists():
            return self.config_path

        found = self.find_config_file(
            self.config_path.name if self.config_path else "pywen_config.yaml"
        )
        if found:
            self.config_path = found
            return found

        raise ConfigError(
            "Pywen config file not found.\n"
            "Please copy an example YAML config "
            "(e.g. pywen_config.example.yaml) "
            "to ~/.pywen/pywen_config.yaml or your project, "
            "or pass --config /path/to/config.yaml."
        )

    @staticmethod
    def _read_yaml(path: Path) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data or {}

    @staticmethod
    def _write_yaml(path: Path, data: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                dict(data),
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
