"""
Loop detection service for QwenAgent to prevent infinite task continuation loops.
Based on qwen-code's LoopDetectionService.
"""

import hashlib
from typing import Optional, Set
from dataclasses import dataclass
from enum import Enum


class LoopType(Enum):
    """Types of loops that can be detected."""
    CONSECUTIVE_IDENTICAL_CONTINUATIONS = "consecutive_identical_continuations"
    REPETITIVE_TASK_ACTIONS = "repetitive_task_actions"


@dataclass
class LoopDetectedEvent:
    """Event data for when a loop is detected."""
    loop_type: LoopType
    repetition_count: int
    detected_pattern: str


class AgentLoopDetectionService:
    """Service for detecting and preventing infinite loops in agent task continuation."""
    
    # Thresholds for different types of loops
    CONTINUATION_LOOP_THRESHOLD = 3  # Max identical continuations
    ACTION_LOOP_THRESHOLD = 5        # Max repetitive actions
    
    def __init__(self):
        # Task continuation tracking
        self.last_continuation_key: Optional[str] = None
        self.continuation_repetition_count: int = 0
        
        # Action pattern tracking
        self.recent_actions: list = []
        self.action_pattern_counts: dict = {}
        
        # General loop prevention
        self.processed_messages: Set[str] = set()
        
    def _get_continuation_key(self, reasoning: str, next_action: str) -> str:
        """Generate a hash key for continuation pattern."""
        pattern = f"{reasoning}:{next_action}"
        return hashlib.sha256(pattern.encode()).hexdigest()[:16]
    
    def _get_action_key(self, action: str) -> str:
        """Generate a hash key for action pattern."""
        # Normalize action text for pattern detection
        normalized = action.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]
    
    def check_continuation_loop(self, reasoning: str, next_action: str) -> Optional[LoopDetectedEvent]:
        """Check if the continuation pattern indicates a loop."""
        key = self._get_continuation_key(reasoning, next_action)
        
        if self.last_continuation_key == key:
            self.continuation_repetition_count += 1
        else:
            self.last_continuation_key = key
            self.continuation_repetition_count = 1
            
        if self.continuation_repetition_count >= self.CONTINUATION_LOOP_THRESHOLD:
            return LoopDetectedEvent(
                loop_type=LoopType.CONSECUTIVE_IDENTICAL_CONTINUATIONS,
                repetition_count=self.continuation_repetition_count,
                detected_pattern=f"Reasoning: {reasoning[:50]}..., Action: {next_action[:50]}..."
            )
        
        return None
    
    def check_action_loop(self, action: str) -> Optional[LoopDetectedEvent]:
        """Check if the action pattern indicates repetitive behavior."""
        action_key = self._get_action_key(action)
        
        # Track recent actions (sliding window)
        self.recent_actions.append(action_key)
        if len(self.recent_actions) > 10:  # Keep last 10 actions
            self.recent_actions.pop(0)
            
        # Count occurrences of this action
        action_count = self.recent_actions.count(action_key)
        
        if action_count >= self.ACTION_LOOP_THRESHOLD:
            return LoopDetectedEvent(
                loop_type=LoopType.REPETITIVE_TASK_ACTIONS,
                repetition_count=action_count,
                detected_pattern=f"Action: {action[:100]}..."
            )
            
        return None
    
    def check_message_repetition(self, message: str) -> bool:
        """Check if we've already processed this exact message."""
        message_hash = hashlib.sha256(message.encode()).hexdigest()
        
        if message_hash in self.processed_messages:
            return True
            
        self.processed_messages.add(message_hash)
        return False
    
    def add_and_check(self, reasoning: str, next_action: str) -> Optional[LoopDetectedEvent]:
        """
        Main method to check for any type of loop.
        Returns LoopDetectedEvent if a loop is detected, None otherwise.
        """
        # Check for continuation loops
        continuation_loop = self.check_continuation_loop(reasoning, next_action)
        if continuation_loop:
            return continuation_loop
            
        # Check for action loops
        action_loop = self.check_action_loop(next_action)
        if action_loop:
            return action_loop
            
        # Check for message repetition
        if self.check_message_repetition(next_action):
            return LoopDetectedEvent(
                loop_type=LoopType.REPETITIVE_TASK_ACTIONS,
                repetition_count=1,
                detected_pattern=f"Repeated message: {next_action[:100]}..."
            )
            
        return None
    
    def reset(self) -> None:
        """Reset all loop detection state."""
        self.last_continuation_key = None
        self.continuation_repetition_count = 0
        self.recent_actions.clear()
        self.action_pattern_counts.clear()
        self.processed_messages.clear()
    
    def reset_continuation_tracking(self) -> None:
        """Reset only continuation tracking (for new tasks)."""
        self.last_continuation_key = None
        self.continuation_repetition_count = 0
