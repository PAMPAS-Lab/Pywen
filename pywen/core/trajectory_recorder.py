"""Trajectory recording functionality."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pywen.utils.llm_basics import LLMMessage, LLMResponse
from pywen.utils.tool_basics import ToolResult, ToolCall
from .session_stats import session_stats


class TrajectoryRecorder:
    """Records trajectory data for agent execution and LLM interactions."""

    def __init__(self, trajectory_path: Optional[Path] = None):
        """Initialize trajectory recorder."""
        if trajectory_path is None:
            from pywen.config.manager import ConfigManager 
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trajectory_path = ConfigManager.get_trajectories_dir() / f"trajectory_{timestamp}.json"

        self.trajectory_path: Path = trajectory_path
        self.trajectory_data: Dict[str, Any] = {
            "start_time": "",
            "end_time": "",
            "provider": "",
            "model": "",
            "max_steps": 0,
            "llm_interactions": [],
            "agent_steps": [],
            "success": False,
            "final_result": None,
            "execution_time": 0.0,
            "total_tokens": 0,  # 添加总token统计
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }
        self._start_time: Optional[datetime] = None

    def start_recording(self, task: str, provider: str, model: str, max_steps: int):
        """Start recording a new trajectory."""
        current_time = datetime.now()
        
        # 如果是第一次记录，设置初始时间
        if self._start_time is None:
            self._start_time = current_time
            self.trajectory_data.update({
                "start_time": self._start_time.isoformat(),
            })
        
        # 对于新任务，可以追加到任务列表或更新当前任务
        if isinstance(self.trajectory_data.get("task"), str):
            # 将单个任务转换为任务列表
            self.trajectory_data["task"] = [self.trajectory_data["task"], task]
        elif isinstance(self.trajectory_data.get("task"), list):
            # 追加新任务到列表
            self.trajectory_data["task"].append(task)
        else:
            # 首次设置任务
            self.trajectory_data["task"] = task
        
        self.trajectory_data.update({
            "provider": provider,
            "model": model,
            "max_steps": max_steps,
        })
        
        # 如果是新任务，才重置interactions和steps
        if not self.trajectory_data.get("llm_interactions"):
            self.trajectory_data["llm_interactions"] = []
        if not self.trajectory_data.get("agent_steps"):
            self.trajectory_data["agent_steps"] = []
        
        self.save_trajectory(show_message=True)

    def record_llm_interaction(
        self,
        messages: List[LLMMessage],
        response: LLMResponse,
        provider: str,
        model: str,
        tools: Optional[List[Any]] = None,
        current_task: Optional[str] = None,
        agent_name: Optional[str] = None,
    ):
        """Record an LLM interaction."""
        # 记录到session stats
        session_stats.record_llm_interaction(
            provider=provider,
            model=model,
            usage=response.usage,
            error=False,
            agent_name=agent_name
        )
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "provider": provider,
            "model": model,
            "current_task": current_task or self._get_current_task(),
            "input_messages": [self._serialize_message(msg) for msg in messages],
            "response": {
                "content": response.content,
                "model": response.model,
                "finish_reason": response.finish_reason,
                "usage": {
                    "input_tokens": response.usage.input_tokens if response.usage else 0,
                    "output_tokens": response.usage.output_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                    "cache_creation_input_tokens": getattr(
                        response.usage, "cache_creation_input_tokens", None
                    ) if response.usage else None,
                    "cache_read_input_tokens": getattr(
                        response.usage, "cache_read_input_tokens", None
                    ) if response.usage else None,
                    "cached_tokens": getattr(response.usage, "cached_tokens", None)
                    if response.usage else None,
                    "reasoning_tokens": getattr(response.usage, "reasoning_tokens", None)
                    if response.usage else None,
                },
                "tool_calls": [self._serialize_tool_call(tc) for tc in response.tool_calls]
                if response.tool_calls else None,
            },
            "tools_available" : [getattr(t, "name", t.get("name") if isinstance(t, dict) else None)
                                for t in tools or [] if getattr(t, "name", None) or (isinstance(t, dict) and t.get("name"))] or None,
        }

        self.trajectory_data["llm_interactions"].append(interaction)
        
        # 更新总token统计
        if response.usage:
            self.trajectory_data["total_input_tokens"] += response.usage.input_tokens or 0
            self.trajectory_data["total_output_tokens"] += response.usage.output_tokens or 0
            self.trajectory_data["total_tokens"] += (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
            self.trajectory_data["context_tokens"] = response.usage.input_tokens or 0
        
        self.save_trajectory()

    def record_agent_step(
        self,
        step_number: int,
        state: str,
        llm_messages: Optional[List[LLMMessage]] = None,
        llm_response: Optional[LLMResponse] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        reflection: Optional[str] = None,
        error: Optional[str] = None,
    ):
        """Record an agent execution step."""
        step_data = {
            "step_number": step_number,
            "timestamp": datetime.now().isoformat(),
            "state": state,
            "llm_messages": [self._serialize_message(msg) for msg in llm_messages]
            if llm_messages else None,
            "llm_response": {
                "content": llm_response.content,
                "model": llm_response.model,
                "finish_reason": llm_response.finish_reason,
                "usage": {
                    "input_tokens": llm_response.usage.input_tokens if llm_response.usage else None,
                    "output_tokens": llm_response.usage.output_tokens if llm_response.usage else None,
                    "total_tokens": llm_response.usage.total_tokens if llm_response.usage else None,
                    "cached_tokens": getattr(llm_response.usage, "cached_tokens", None)
                    if llm_response.usage else None,
                } if llm_response.usage else None,
                "tool_calls": [self._serialize_tool_call(tc) for tc in llm_response.tool_calls]
                if llm_response.tool_calls else None,
            } if llm_response else None,
            "tool_calls": [self._serialize_tool_call(tc) for tc in tool_calls]
            if tool_calls else None,
            "tool_results": [self._serialize_tool_result(tr) for tr in tool_results]
            if tool_results else None,
            "reflection": reflection,
            "error": error,
        }

        self.trajectory_data["agent_steps"].append(step_data)
        self.save_trajectory()

    def finalize_recording(self, success: bool, final_result: Optional[str] = None):
        """Finalize the trajectory recording."""
        end_time = datetime.now()
        self.trajectory_data.update({
            "end_time": end_time.isoformat(),
            "success": success,
            "final_result": final_result,
            "execution_time": (end_time - self._start_time).total_seconds() if self._start_time else 0.0,
        })
        self.save_trajectory()

    def save_trajectory(self, show_message: bool = False):
        """Save the current trajectory data to file."""
        try:
            # 确保目录存在
            self.trajectory_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.trajectory_path, "w", encoding="utf-8") as f:
                json.dump(self.trajectory_data, f, indent=2, ensure_ascii=False)

            # 只在明确要求时才显示消息
            if show_message:
                print(f"✅ Trajectory saved to: {self.trajectory_path}")

        except Exception as e:
            print(f"❌ Warning: Failed to save trajectory to {self.trajectory_path}: {e}")

    def _serialize_message(self, message: LLMMessage) -> Dict[str, Any]:
        """Serialize an LLM message to a dictionary."""
        data = {"role": message.role, "content": message.content}

        if hasattr(message, 'tool_call') and message.tool_call:
            data["tool_call"] = self._serialize_tool_call(message.tool_call)

        if hasattr(message, 'tool_result') and message.tool_result:
            data["tool_result"] = self._serialize_tool_result(message.tool_result)

        # 兼容旧版本
        if hasattr(message, 'tool_calls') and message.tool_calls:
            data["tool_calls"] = [self._serialize_tool_call(tc) for tc in message.tool_calls]

        if hasattr(message, 'tool_call_id') and message.tool_call_id:
            data["tool_call_id"] = message.tool_call_id

        return data

    def _serialize_tool_call(self, tool_call: ToolCall) -> Dict[str, Any]:
        """Serialize a tool call to a dictionary."""
        return {
            "call_id": tool_call.call_id,
            "name": tool_call.name,
            "arguments": tool_call.arguments,
            "id": getattr(tool_call, "id", None),
        }

    def _serialize_tool_result(self, tool_result: ToolResult) -> Dict[str, Any]:
        """Serialize a tool result to a dictionary."""
        return {
            "call_id": tool_result.call_id,
            "success": tool_result.success,
            "result": tool_result.result,
            "error": tool_result.error,
            "id": getattr(tool_result, "id", None),
        }

    def get_trajectory_path(self) -> str:
        """Get the path where trajectory is being saved."""
        return str(self.trajectory_path)

    def _get_current_task(self) -> Optional[str]:
        """Get the current task being executed."""
        task = self.trajectory_data.get("task")
        if isinstance(task, list):
            return task[-1] if task else None
        return task
