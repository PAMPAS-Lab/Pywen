from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    model_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    class ConfigDict:
        extra = "allow"

class AgentConfig(BaseModel):
    agent_name: str
    provider: Literal["openai", "anthropic", None] = None
    wire_api : Literal["chat", "responses", None] = None
    model: ModelConfig
    class ConfigDict:
        extra = "allow"

class MCPServerConfig(BaseModel):
    name: str
    type: str = "stdio"
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
    rules: List[Tuple[float, int]] = Field(default_factory=list)
    model: Optional[str] = None
    class ConfigDict:
        extra = "allow"

class AppConfig(BaseModel):
    default_agent: Optional[str] = None
    agents: List[AgentConfig]
    permission_level: str = "locked"
    max_turns: int = 20
    enable_logging: bool = True
    log_level: str = "INFO"

    mcp: Optional[MCPConfig] = None
    memory_monitor: Optional[MemoryMonitorConfig] = None

    runtime: Dict[str, Any] = Field(default_factory=dict)

    class ConfigDict:
        extra = "allow"
