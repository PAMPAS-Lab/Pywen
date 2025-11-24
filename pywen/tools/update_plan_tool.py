from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Mapping
from .base_tool import BaseTool, ToolResult, ToolRiskLevel
from pywen.core.tool_registry2 import register_tool

class PlanItemStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    SKIPPED = "skipped"

def _validate_plan_items(items: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """Check schema and 'single in_progress' constraint."""
    in_prog = 0
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            return False, f"Plan item at index {idx} is not an object"
        if "step" not in it or not isinstance(it["step"], str) or not it["step"].strip():
            return False, f"Plan item {idx} missing non-empty 'step'"
        if "status" not in it or not isinstance(it["status"], str):
            return False, f"Plan item {idx} missing 'status'"
        try:
            status = PlanItemStatus(it["status"])
        except Exception:
            return False, f"Plan item {idx} has invalid status '{it['status']}'"
        if status == PlanItemStatus.IN_PROGRESS:
            in_prog += 1
    if in_prog > 1:
        return False, "At most one plan item can be 'in_progress'"
    return True, None

def _render_markdown(explanation: Optional[str], items: List[Dict[str, Any]]) -> str:
    lines = ["# Updated Plan"]
    if explanation:
        lines.append(f"\n**Explanation**: {explanation}")
    lines.append("\n**Steps**:")
    status_emoji = {
        "todo": "📝",
        "in_progress": "🏃",
        "done": "✅",
        "blocked": "⛔",
        "skipped": "⤴️",
    }
    for i, it in enumerate(items, 1):
        s = it["status"]
        em = status_emoji.get(s, "•")
        lines.append(f"- {em} **{it['step']}**  _({s})_")
    return "\n".join(lines)

@register_tool(name="update_plan", providers=["codex"])
class UpdatePlanTool(BaseTool):
    name="update_plan"
    display_name="Update Plan"
    description=(
        "Updates the task plan.Provide an optional explanation and a list of plan items, each with a step and status.At most one step can be in_progress at a time."
    )
    parameter_schema={
        "type": "object",
        "properties": {
            "explanation": {"type": "string", "description": "Optional rationale for the change."},
            "plan": {
                "type": "array",
                "description": "List of plan items to set (full replacement).",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["todo", "in_progress", "done", "blocked", "skipped"],
                        },
                    },
                    "required": ["step", "status"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["plan"],
        "additionalProperties": False,
    }

    async def execute(self, **kwargs) -> ToolResult:
        explanation: Optional[str] = kwargs.get("explanation")
        items = kwargs.get("plan")
        if not isinstance(items, list):
            return ToolResult(call_id="", error="'plan' must be a list of {step, status} objects")

        ok, err = _validate_plan_items(items)
        if not ok:
            return ToolResult(call_id="", error=err or "Invalid plan")

        normalized: List[Dict[str, str]] = []
        for it in items:
            normalized.append({"step": it["step"].strip(), "status": PlanItemStatus(it["status"]).value})

        md = _render_markdown(explanation, normalized)

        payload = {
            "explanation": explanation or "",
            "plan": normalized,
        }

        return ToolResult(call_id="", result=md, metadata={"payload": payload})

    def build(self, provider:str = "", func_type: str = "") -> Mapping[str, Any]:
        """ codex专用 """
        return {
                "type" : "function",
                "name" : self.name,
                "description": self.description,
                "strict": False,
                "parameters": self.parameter_schema,
                }
