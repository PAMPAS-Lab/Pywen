from __future__ import annotations
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field

class ModelConfig(BaseModel):
    agent_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    provider: Literal["openai", "anthropic", None] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    wire_api : Literal["chat", "responses", None] = None
    class ConfigDict:
        extra = "allow"

class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: List[str] = Field(default_factory=list)
    enabled: bool = True
    include: List[str] = Field(default_factory=list)
    save_images_dir: Optional[str] = None
    isolated: bool = False
    class ConfigDict:
        extra = "allow"

class MCPConfig(BaseModel):
    enabled: bool = True
    isolated: bool = False
    servers: List[MCPServerConfig] = Field(default_factory=list)
    class ConfigDict:
        extra = "allow"

class MemoryMonitorConfig(BaseModel):
    check_interval: int = 60
    maximum_capacity: int = 4096
    rules: List[List[float]] = Field(default_factory=list)
    model: Optional[str] = None
    class ConfigDict:
        extra = "allow"

class AppConfig(BaseModel):
    default_agent: Optional[str] = None
    models: List[ModelConfig]
    permission_level: str = "locked"
    max_turns: int = 10
    enable_logging: bool = True
    log_level: str = "INFO"

    mcp: Optional[MCPConfig] = None
    memory_monitor: Optional[MemoryMonitorConfig] = None

    runtime: Dict[str, Any] = Field(default_factory=dict)

    class ConfigDict:
        extra = "allow"

    @property
    def active_agent_name(self) -> str:
        """当前激活的 agent 名称"""
        name = self.runtime.get("active_agent")
        if isinstance(name, str) and name.strip():
            return name.strip()

        if isinstance(self.default_agent, str) and self.default_agent.strip():
            return self.default_agent.strip()

        if len(self.models) == 1:
            return self.models[0].agent_name

        raise ValueError(
            "Active agent is not determined. "
            "Set 'default_agent' in config or runtime.active_agent."
        )

    @property
    def active_model(self) -> ModelConfig:
        """ 
        返回当前激活的 ModelConfig 
        利用agentg与model的映射关系找到对应的model配置。
        如果一个agent对应多个model配置，则此方法需要扩展。
        """
        name = self.active_agent_name
        for p in self.models:
            if p.agent_name == name:
                return p
        raise ValueError(f"Active agent '{name}' not found in agents.")

    def set_active_agent(self, name: str) -> None:
        """
        切换当前激活agent。
        只允许切到已配置的 agent，否则直接报错。
        """
        name = name.strip().lower()
        if not name:
            raise ValueError("agent name cannot be empty.")

        if name.endswith("agent"):
            name = name[: -len("agent")]
        if not any(m.agent_name == name for m in self.models):
            raise ValueError(f"Model '{name}' not found in models.")

        self.runtime["active_agent"] = name
