from __future__ import annotations
import os,sys
import yaml
import stat
import shutil
import importlib.resources as pkgres
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from .config import AppConfig, AgentConfig, ModelConfig
from pywen.skills import SkillsManager, render_skills_section

PLACEHOLDERS = {
    "your-qwen-api-key-here",
    "changeme",
    "placeholder",
    "your_api_key_here",
}
EDIT_HINT_FIELDS = (
    "model",
    "api_key",
    "base_url",
)

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

    @classmethod
    def find_config_file(cls, filename: str = "pywen_config.yaml") -> Optional[Path]:
        candidates = [cls.get_default_config_path(), Path.cwd() / filename]
        for parent in Path.cwd().parents:
            candidates.append(parent / filename)
        for p in candidates:
            if p.exists():
                return p
        return None

    def get_raw_config(self) -> Dict[str, Any]:
        if self._raw_config is None:
            return self._load_raw()
        return self._raw_config

    def resolve_effective_config(self, args: Any | None = None) -> AppConfig:
        """ 合并 YAML + CLI + ENV 后的配置，返回最终 AppConfig。允许不传 args。 """
        raw = self.get_raw_config()

        agents = self._normalize_and_check_agents(raw)
        agents_by_name = self._index_agents(agents)

        active_name = self._select_active_agent_name(raw, agents_by_name, args)
        active_agent_cfg = agents_by_name[active_name]

        self._apply_field_priority(active_agent_cfg, active_name, args)

        missing = self._find_missing_required_fields(active_agent_cfg)
        if missing:
            cfg = str(self.config_path) if self.config_path else "<unknown config>"
            print(
                "Configuration file:\n"
                f"  {cfg}\n\n"
                f"Missing required fields for agent '{active_name}':\n"
                + "".join(f"  - {field}\n" for field in missing)
                + "\nPlease update the configuration file, environment variables, "
                "or CLI arguments.",
                file=sys.stderr,
            )
            sys.exit(2)

        runtime = raw.setdefault("runtime", {})
        runtime["active_agent"] = active_name

        cli_perm = getattr(args, "permission_mode", None) if args is not None else None
        if isinstance(cli_perm, str) and cli_perm.strip():
            raw["permission_level"] = cli_perm.strip()

        app_cfg = AppConfig.model_validate(raw)
        self._app_config = app_cfg
        return app_cfg

    def get_app_config(self, args: Any | None = None) -> AppConfig:
        if self._app_config is None:
            return self.resolve_effective_config(args)
        return self._app_config

    def get_active_agent(self, args: Any | None = None) -> AgentConfig:
        app = self.get_app_config(args)
        name = self.get_active_agent_name(args)
        for ag in app.agents:
            if ag.agent_name == name:
                return ag
        if app.agents:
            return app.agents[0]
        raise ConfigError("No agents configured.")

    def get_active_agent_name(self, args: Any | None = None) -> str:
        app = self.get_app_config(args)
        runtime_name = app.runtime.get("active_agent") if app.runtime else None
        if isinstance(runtime_name, str) and runtime_name.strip():
            return runtime_name.strip()

        raw = self.get_raw_config()
        agents = self._normalize_and_check_agents(raw)
        agents_by_name = self._index_agents(agents)
        return self._select_active_agent_name(raw, agents_by_name, args)

    def get_active_model(self, args: Any | None = None) -> ModelConfig:
        return self.get_active_agent(args).model

    def get_active_model_name(self, args: Any | None = None) -> str:
        return self.get_active_model(args).model_name

    def get_active_model_max_tokens(self, args: Any | None = None, default: int = 4096) -> int:
        return self.get_active_model(args).max_tokens or default
    def list_agent_names(self, args: Any | None = None) -> List[str]:
        cfg = self._app_config if self._app_config else self.resolve_effective_config(args)
        return [ag.agent_name for ag in cfg.agents]

    def switch_active_agent(self, agent_name: str, args: Any | None = None) -> AppConfig:
        raw = self.get_raw_config()

        agents = self._normalize_and_check_agents(raw)
        agents_by_name = self._index_agents(agents)

        name = agent_name.strip()
        if name.lower().endswith("agent"):
            name = name[: -len("agent")]
        if name not in agents_by_name:
            raise ConfigError(f"Agent '{name}' is not defined in 'agents'.")

        agent_cfg = agents_by_name[name]
        self._apply_field_priority(agent_cfg, name, args)

        missing = self._find_missing_required_fields(agent_cfg)
        if missing:
            cfg = str(self.config_path) if self.config_path else "<unknown config>"
            raise ConfigError(
                f"'{cfg}' missing required fields in agent '{name}': {missing}. "
                "Please update your YAML/ENV/CLI."
            )

        runtime = raw.setdefault("runtime", {})
        runtime["active_agent"] = name

        cli_perm = getattr(args, "permission_mode", None) if args is not None else None
        if isinstance(cli_perm, str) and cli_perm.strip():
            raw["permission_level"] = cli_perm.strip()

        app_cfg = AppConfig.model_validate(raw)
        self._app_config = app_cfg
        return app_cfg

    def get_md_prompt(self, args: Any | None = None) -> str:
        """ 获取项目MD专用配置 """
        app_cfg = self.get_app_config(args)
        runtime = app_cfg.runtime
        filename = "PYWEN.md"
        parts: list[str] = []
        current_dir = Path.cwd().resolve()
        max_hops = 512
        hops = 0
        while True:
            md_path = current_dir / filename
            if md_path.is_file():
                try:
                    content = md_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = md_path.read_text(encoding="utf-8", errors="replace")
                parts.append(f"Contents of {md_path}:\n\n{content}")

            parent = current_dir.parent
            if parent == current_dir:
                break
            current_dir = parent
            hops += 1
            if hops >= max_hops:
                break
        if not parts:
            return ""

        parts.reverse()
        STYLE_PROMPT = (
            "The codebase follows strict style guidelines shown below. "
            "All code changes must strictly adhere to these guidelines to maintain "
            "consistency and quality."
        )
        md_prompt = f"{STYLE_PROMPT}\n\n" + "\n\n".join(parts)
        runtime["md_prompt"] = md_prompt

        return md_prompt

    def get_skills_prompt(self, args: Any | None = None) -> str:
        """ 获取项目Skills专用配置 """
        skill_mgr = SkillsManager(self.get_pywen_config_dir())
        outcome = skill_mgr.skills_for_cwd()
        skills_section: Optional[str] = None
        if not outcome.errors and outcome.skills:
            skills_section = render_skills_section(outcome.skills)
        app_cfg = self.get_app_config(args)
        app_cfg.runtime["skills_prompt"] = skills_section

        return skills_section or ""

    def _resolve_config_path(self) -> Path:
        """
        寻找最终配置文件路径：
        1) 若 self.config_path 存在 → 返回
        2) 若可在默认/工作目录/父目录找到 → 返回
        3) 否则尝试寻找 example，找到则复制到 ~/.pywen/pywen_config.yaml 并提示
        4) 都没有 → 抛出包含操作指引的 ConfigError
        """
        if self.config_path and self.config_path.exists():
            return self.config_path

        found = self.find_config_file(
            self.config_path.name if self.config_path else "pywen_config.yaml"
        )
        if found:
            self.config_path = found
            return found

        example = self._locate_example_config()
        if example is not None:
            target = self.get_default_config_path()
            if not target.exists():
                try:
                    self._atomic_copy(example, target)
                    self._chmod_private(target)
                    self._print_copy_hint(example, target)
                    self.config_path = target
                    return target
                except Exception as e:
                    raise ConfigError(
                        "Found example config but failed to copy to default location.\n"
                        f"Source: {example}\nTarget: {target}\nError: {e}"
                    ) from e
            else:
                self.config_path = target
                return target

        default_path = self.get_default_config_path()
        searched = [default_path, Path.cwd() / "pywen_config.yaml", *[p / "pywen_config.yaml" for p in Path.cwd().parents]]
        searched_list = "\n  - " + "\n  - ".join(str(p) for p in searched)
        raise ConfigError(
            "Pywen config file not found.\n"
            "Searched locations:" + searched_list + "\n"
            f'You may copy an example file named one of pywen_config.example.yaml into "{default_path}".\n'
            "Or set environment variables to run without a file:\n"
            "  export PYWEN_MODEL='xxx'\n"
            "  export PYWEN_API_KEY='sk-...'\n"
            "  export PYWEN_BASE_URL='https://xx.xx.xx/'\n"
            "Or pass --config /path/to/pywen_config.yaml\n"
        )

    def _load_raw(self) -> Dict[str, Any]:
        path = self._resolve_config_path()
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ConfigError(f"Config file must be a mapping (YAML dict): {path}")
        self._raw_config = data
        return data

    @staticmethod
    def _build_model_from_agent_fields(ag: Dict[str, Any]) -> Dict[str, Any]:
        m = ag.get("model")
        if isinstance(m, dict):
            model_obj = dict(m)
        else:
            model_obj = {"model_name": (m or "")}
        if "api_key" in ag and "api_key" not in model_obj:
            model_obj["api_key"] = ag["api_key"]
        if "base_url" in ag and "base_url" not in model_obj:
            model_obj["base_url"] = ag["base_url"]
        for k in ("temperature", "max_tokens", "top_p", "top_k"):
            if k in ag and k not in model_obj:
                model_obj[k] = ag[k]
        model_obj.setdefault("model_name", "")
        model_obj.setdefault("api_key", "")
        model_obj.setdefault("base_url", "")
        return model_obj

    @staticmethod
    def _normalize_and_check_agents(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        agents = raw.get("agents", [])
        if not isinstance(agents, list):
            raise ConfigError("Config field 'agents' must be a list.")
        if not agents:
            raise ConfigError("'agents' list is empty.")

        seen = set()
        for ag in agents:
            if not isinstance(ag, dict):
                raise ConfigError("Each item in 'agents' must be a mapping.")
            name = ag.get("agent_name")
            if not isinstance(name, str) or not name.strip():
                raise ConfigError("Each agent must have a non-empty 'agent_name'.")
            key = name.strip()
            if key in seen:
                raise ConfigError(f"Duplicate agent_name: {key}")
            seen.add(key)
            ag["model"] = ConfigManager._build_model_from_agent_fields(ag)

        return agents

    @staticmethod
    def _index_agents(agents: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {ag["agent_name"].strip(): ag for ag in agents}

    @staticmethod
    def _is_missing(val: Any) -> bool:
        if val is None:
            return True
        s = str(val).strip()
        if not s:
            return True
        return s.lower() in PLACEHOLDERS

    @staticmethod
    def _normalize_field(field: str, value: Any) -> Any:
        if value is None:
            return None
        if field == "base_url":
            return str(value).strip().rstrip("/")
        if field in ("api_key", "model"):
            return str(value).strip()
        return value

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
            f"{name_up}_{key_suffix}",
            key_suffix,
        ]
        for k in candidates:
            v = os.getenv(k)
            if v and str(v).strip():
                return str(v).strip()
        return None

    @staticmethod
    def _find_missing_required_fields(agent_cfg: Mapping[str, Any]) -> List[str]:
        m = agent_cfg.get("model", {})
        if not isinstance(m, dict):
            return ["model (must be an object)"]

        missing: List[str] = []
        if ConfigManager._is_missing(m.get("model_name")):
            missing.append("model")
        if ConfigManager._is_missing(m.get("api_key")):
            missing.append("api_key")
        if ConfigManager._is_missing(m.get("base_url")):
            missing.append("base_url")
        return missing

    def _select_active_agent_name(
        self,
        raw_cfg: Mapping[str, Any],
        agents_by_name: Mapping[str, Dict[str, Any]],
        args: Any | None,
    ) -> str:
        """ 选择当前 active agent 名称 """
        cli_agent = getattr(args, "agent", None) if args is not None else None
        if isinstance(cli_agent, str) and cli_agent.strip():
            name = cli_agent.strip()
            if name not in agents_by_name:
                raise ConfigError(
                    f"CLI requested agent '{name}', but it's not found in 'agents'."
                )
            return name

        default_agent = raw_cfg.get("default_agent")
        if isinstance(default_agent, str) and default_agent.strip():
            name = default_agent.strip()
            if name not in agents_by_name:
                raise ConfigError(
                    f"default_agent '{name}' is not defined in 'agents'."
                )
            return name

        if len(agents_by_name) == 1:
            return next(iter(agents_by_name.keys()))

        raise ConfigError(
            "No agent selected and 'default_agent' is not set, "
            "while multiple agents are configured. "
            "Please set 'default_agent' or use --agent."
        )

    def _apply_field_priority(
        self,
        agent_cfg: Dict[str, Any],
        agent_name: str,
        args: Any | None,
    ) -> None:
        cli_fields = ("model", "api_key", "base_url", "temperature", "max_tokens", "top_p", "top_k")
        m = agent_cfg["model"]

        for field in cli_fields:
            # 1) CLI
            cli_value = getattr(args, field, None) if args is not None else None
            if cli_value is not None:
                if field == "model":
                    m["model_name"] = self._normalize_field("model", cli_value)
                else:
                    m[field] = self._normalize_field(field, cli_value)
                continue

            # 2) YAML 原值
            current = m.get("model_name") if field == "model" else m.get(field)
            if not self._is_missing(current):
                if field == "model":
                    m["model_name"] = self._normalize_field("model", current)
                else:
                    m[field] = self._normalize_field(field, current)
                continue

            # 3) ENV
            if field in ("api_key", "base_url", "model"):
                env_val = self._get_env_for_field(field, agent_name)
                if env_val is not None:
                    if field == "model":
                        m["model_name"] = self._normalize_field("model", env_val)
                    else:
                        m[field] = self._normalize_field(field, env_val)

    @classmethod
    def _locate_example_config(cls) -> Optional[Path]:
        """
        1) 优先从 package resources 读取
        2) 开发态 fallback：直接从 pywen/config 目录查找
        """
        EXAMPLE_FILENAME = "pywen_config.example.yaml"

        # 安装态：package resources
        try:
            res = pkgres.files("pywen.config").joinpath(EXAMPLE_FILENAME)
            if res.is_file():
                with pkgres.as_file(res) as fp:
                    return Path(fp)
        except Exception:
            pass

        # 开发态 
        here = Path(__file__).resolve()
        p = here.parent / EXAMPLE_FILENAME
        if p.exists():
            return p

        return None

    def _atomic_copy(self, src: Path, dst: Path) -> None:
        """原子复制，避免并发读写时的半成品文件。"""
        dst.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(dst.parent)) as tf:
            with open(src, "rb") as sf:
                shutil.copyfileobj(sf, tf)
            tmp = Path(tf.name)
        os.replace(tmp, dst)

    def _chmod_private(self, path: Path) -> None:
        """在 *nix 上将权限收紧到 0o600；Windows 忽略。"""
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass

    def _print_copy_hint(self, example_src: Path, target: Path) -> None:
        """在交互终端输出一次拷贝提示与需要修改的关键字段。"""
        if sys.stderr.isatty():
            print(
                    "\n[Pywen] 未找到配置文件，已从示例复制默认配置：\n"
                    f"  源: {example_src}\n"
                    f"  目标: {target}\n\n"
                    "请至少检查/修改以下字段以确保可用：\n"
                    + "".join(f"  - {f}\n" for f in EDIT_HINT_FIELDS),
                    file=sys.stderr,
            )
