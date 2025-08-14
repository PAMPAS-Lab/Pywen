"""Task continuation checker - determines if task needs more turns."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass

from pywen.utils.llm_basics import LLMMessage
from pywen.utils.llm_client import LLMClient
from pywen.utils.llm_config import Config


@dataclass
class TaskContinuationResponse:
    """Response from task continuation check."""
    reasoning: str
    should_continue: bool
    next_speaker: str  # 'user' or 'model'
    next_action: Optional[str] = None


class TaskContinuationChecker:
    """Checks if a task needs continuation using LLM-based analysis."""
    
    CHECK_PROMPT = """You are analyzing whether a task needs continuation based on the agent's last response.

**Context:**
- Original Task: {original_task}
- Last Agent Response: {last_response}
- Conversation Summary: {conversation_summary}

**Decision Rules (apply in order):**
1. **Task Complete**: If the response provides comprehensive analysis, concludes with "in summary/conclusion", explicitly states completion, or fully answers the original question, then should_continue=false.
2. **User Input Needed**: If the response asks a direct question to the user, requests user clarification, or waits for user input (e.g., "Which programming language?", "Please specify..."), then should_continue=true and next_speaker='user'.
3. **Model Continues**: If the response indicates incomplete work, mentions "preliminary", "initial", "need more research", suggests further steps, or seems cut off mid-analysis, then should_continue=true and next_speaker='model'.

**Output Format:**
Respond in JSON format:
```json
{{
  "reasoning": "Brief explanation of the decision based on applicable rule",
  "should_continue": true/false,
  "next_speaker": "user/model (only if should_continue=true)",
  "next_action": "Optional: specific next step if continuing"
}}
```"""
    
    def __init__(self, llm_client: LLMClient, config: Config):
        self.llm_client = llm_client
        self.config = config
        self.cli_console = None  # 添加cli_console引用
        
        # Setup logger for task continuation decisions
        self._setup_logger()
        
        # 用于记录最后一次LLM调用
        self.last_messages = None
        self.last_llm_response = None
    
    def set_cli_console(self, cli_console):
        """Set CLI console for debug output."""
        self.cli_console = cli_console
    
    def _setup_logger(self):
        """Setup logger for task continuation decisions."""
        # Create logs directory if it doesn't exist
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # Setup logger
        self.logger = logging.getLogger("task_continuation")
        self.logger.setLevel(logging.INFO)
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # File handler
        log_file = log_dir / "task_continuation.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
    
    async def check_task_continuation(
        self,
        original_task: str,
        last_response: str,
        conversation_history: List[LLMMessage],
        max_turns_reached: bool = False
    ) -> Optional[TaskContinuationResponse]:
        """
        Check if the task needs continuation.
        
        Args:
            original_task: The original user request
            last_response: The agent's last response
            conversation_history: Full conversation history
            max_turns_reached: Whether max turns limit has been reached
            
        Returns:
            TaskContinuationResponse or None if check failed
        """
        
        # If max turns reached, don't continue
        if max_turns_reached:
            return TaskContinuationResponse(
                reasoning="Maximum number of turns reached, stopping task execution.",
                should_continue=False,
                next_speaker="user"
            )
        
        # If no conversation history, can't determine
        if not conversation_history:
            return None
        
        # Remove the length-based check - let LLM decide based on content quality
        if not last_response:
            return TaskContinuationResponse(
                reasoning=None,
                should_continue=True,
                next_action=None
            )
        
        try:
            # Create conversation summary
            conversation_summary = self._create_conversation_summary(conversation_history)
            
            # Format the check prompt
            check_prompt = self.CHECK_PROMPT.format(
                original_task=original_task,
                last_response=last_response,  # 移除长度限制
                conversation_summary=conversation_summary
            )
            
            # Prepare messages for LLM
            messages = [
                LLMMessage(role="user", content=check_prompt)
            ]
            
            # 保存messages用于trajectory记录
            self.last_messages = messages
            
            # Generate LLM response for continuation check
            response = await self.llm_client.generate_response(
                messages=messages,
                tools=None
            )
            
            # 保存response用于trajectory记录
            self.last_llm_response = response
            
            if not response or not response.content:
                return None
            
            # 添加调试输出 - 通过cli_console显示
            if self.cli_console:
                self.cli_console.print(f"🔍 [yellow]DEBUG: LLM Raw Response for Task Continuation:[/yellow]")
                self.cli_console.print(f"   Content: {response.content}")
                self.cli_console.print(f"   Content Type: {type(response.content)}")
                self.cli_console.print(f"   Content Length: {len(response.content) if response.content else 0}")
                self.cli_console.print("─" * 60)
            
            # Parse JSON response
            try:
                # 先尝试提取JSON代码块中的内容
                content = response.content.strip()
                
                # 检查是否包含在代码块中
                if content.startswith('```json') and content.endswith('```'):
                    # 提取代码块中的JSON内容
                    json_content = content[7:-3].strip()  # 移除```json和```
                elif content.startswith('```') and content.endswith('```'):
                    # 提取普通代码块中的内容
                    json_content = content[3:-3].strip()  # 移除```
                else:
                    # 直接使用原内容
                    json_content = content
                
                if self.cli_console:
                    self.cli_console.print(f"🔧 [blue]DEBUG: Extracted JSON content:[/blue]")
                    self.cli_console.print(f"   '{json_content}'")
                
                parsed_response = json.loads(json_content)
                
                # Validate required fields
                required_fields = ["reasoning", "should_continue"]
                if parsed_response.get("should_continue"):
                    required_fields.append("next_speaker")
                
                if not all(key in parsed_response for key in required_fields):
                    if self.cli_console:
                        self.cli_console.print(f"❌ [red]DEBUG: Missing required fields in parsed response: {parsed_response}[/red]")
                    return None
                
                response_obj = TaskContinuationResponse(
                    reasoning=parsed_response["reasoning"],
                    should_continue=bool(parsed_response["should_continue"]),
                    next_speaker=parsed_response.get("next_speaker", "user"),
                    next_action=parsed_response.get("next_action")
                )
                
                if self.cli_console:
                    self.cli_console.print(f"✅ [green]DEBUG: Successfully parsed JSON response:[/green]")
                    self.cli_console.print(f"   Should Continue: {response_obj.should_continue}")
                    self.cli_console.print(f"   Reasoning: {response_obj.reasoning}")
                    self.cli_console.print(f"   Next Action: {response_obj.next_action}")
                    self.cli_console.print("─" * 60)
                
                # Log the continuation decision to file
                log_data = {
                    "task_continuation_decision": {
                        "should_continue": response_obj.should_continue,
                        "reasoning": response_obj.reasoning,
                        "next_action": response_obj.next_action,
                        "turn_count": len(conversation_history) // 2 if conversation_history else 0,
                        "timestamp": datetime.now().isoformat()
                    }
                }
                self.logger.info(json.dumps(log_data, ensure_ascii=False))
                
                return response_obj
                
            except json.JSONDecodeError as e:
                if self.cli_console:
                    self.cli_console.print(f"❌ [red]DEBUG: JSON parsing failed: {e}[/red]")
                    self.cli_console.print(f"   Raw content: '{response.content}'")
                    self.cli_console.print(f"   Attempting fallback parsing...")
                
                # Fallback: try to extract decision from text
                content_lower = response.content.lower()
                if "should_continue" in content_lower:
                    should_continue = "true" in content_lower
                    if self.cli_console:
                        self.cli_console.print(f"🔄 [yellow]DEBUG: Fallback parsing result: should_continue={should_continue}[/yellow]")
                    return TaskContinuationResponse(
                        reasoning="Parsed from non-JSON response",
                        should_continue=should_continue
                    )
                if self.cli_console:
                    self.cli_console.print(f"❌ [red]DEBUG: Fallback parsing also failed[/red]")
                return None
                
        except Exception as e:
            print(f"❌ Error in task continuation check: {e}")
            return None
    
    def _create_conversation_summary(self, conversation_history: List[LLMMessage]) -> str:
        """Create a concise summary of the conversation for context."""
        if not conversation_history:
            return "No conversation history available."
        
        # 移除消息数量限制，使用完整对话历史
        summary_parts = []
        for msg in conversation_history:
            role = msg.role.upper()
            content = msg.content  # 移除内容长度限制
            summary_parts.append(f"{role}: {content}")

        return "\n".join(summary_parts)
    
    def should_continue_based_on_heuristics(
        self,
        original_task: str,
        last_response: str,
        turn_count: int
    ) -> bool:
        """
        Fallback heuristic-based continuation check.
        Used when LLM check fails.
        """
        
        # Simple heuristics
        task_lower = original_task.lower()
        response_lower = last_response.lower()
        
        # Research/analysis tasks often need multiple turns
        research_keywords = ["research", "analyze", "investigate", "explore", "study", "examine"]
        is_research_task = any(keyword in task_lower for keyword in research_keywords)
        
        # Check if response indicates incompleteness
        incomplete_indicators = [
            "need more", "should investigate", "requires further", "more research needed",
            "preliminary", "initial findings", "surface level", "brief overview"
        ]
        seems_incomplete = any(indicator in response_lower for indicator in incomplete_indicators)
        
        # Check if response indicates completion
        completion_indicators = [
            "in conclusion", "to summarize", "final analysis", "comprehensive overview",
            "task completed", "analysis complete", "research finished"
        ]
        seems_complete = any(indicator in response_lower for indicator in completion_indicators)
        
        # Decision logic
        should_continue = False
        reasoning = ""
        
        if seems_complete:
            should_continue = False
            reasoning = "Response contains completion indicators"
        elif seems_incomplete:
            should_continue = True
            reasoning = "Response contains incompleteness indicators"
        elif is_research_task and turn_count < 3:
            should_continue = True
            reasoning = "Research task needs multiple iterations"
        elif turn_count == 1:
            should_continue = True
            reasoning = "First turn likely needs more development"
        else:
            should_continue = False
            reasoning = "Default to not continuing"
        
        # Log heuristic decision
        log_data = {
            "heuristic_continuation_decision": {
                "should_continue": should_continue,
                "reasoning": reasoning,
                "turn_count": turn_count,
                "is_research_task": is_research_task,
                "seems_complete": seems_complete,
                "seems_incomplete": seems_incomplete,
                "timestamp": datetime.now().isoformat()
            }
        }
        self.logger.info(json.dumps(log_data, ensure_ascii=False))
        
        return should_continue



















