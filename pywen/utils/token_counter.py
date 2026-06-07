"""
Simple and efficient token counting utilities
Based on Kode's lightweight approach
"""

from typing import Any, Dict, List

from .llm_basics import LLMMessage


def count_tokens_from_messages(messages: List[LLMMessage]) -> int:
    """
    Count tokens from message history using the last assistant response's usage info.
    This is the Kode approach - simple and efficient.
    """
    # Search backwards for the most recent assistant message with usage info
    for i in range(len(messages) - 1, -1, -1):
        message = messages[i]
        
        # Skip if not assistant message
        if message.role != "assistant":
            continue
            
        # Check if this message has usage information
        if hasattr(message, 'usage') and message.usage:
            usage = message.usage
            return (
                usage.input_tokens +
                getattr(usage, 'cache_creation_input_tokens', 0) +
                getattr(usage, 'cache_read_input_tokens', 0) +
                usage.output_tokens
            )
    
    # No usage info found, return 0
    return 0


def count_cached_tokens_from_messages(messages: List[LLMMessage]) -> int:
    """
    Count cached tokens from message history.
    """
    # Search backwards for the most recent assistant message with usage info
    for i in range(len(messages) - 1, -1, -1):
        message = messages[i]
        
        if message.role != "assistant":
            continue
            
        if hasattr(message, 'usage') and message.usage:
            usage = message.usage
            return (
                getattr(usage, 'cache_creation_input_tokens', 0) +
                getattr(usage, 'cache_read_input_tokens', 0)
            )
    
    return 0


def estimate_tokens_simple(text: str, provider: str = "qwen") -> int:
    """
    Simple token estimation based on character count.
    Much lighter than loading a full tokenizer.
    """
    if not text:
        return 0
    
    char_count = len(text)
    
    # Different ratios for different providers/languages
    if provider.lower() == "qwen":
        # Chinese content has higher token density
        return max(1, char_count // 2)
    elif provider.lower() in ["openai", "anthropic"]:
        # English content standard ratio
        return max(1, char_count // 4)
    else:
        # Conservative estimate
        return max(1, char_count // 3)


def estimate_tokens_from_messages(messages: List[LLMMessage], provider: str = "qwen") -> int:
    """
    Estimate tokens from messages using simple character counting.
    Fallback when no usage info is available.
    """
    total_chars = 0
    
    for msg in messages:
        # Count text content
        if msg.content:
            total_chars += len(msg.content)
        
        # Count tool calls (simplified)
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tool_call in msg.tool_calls:
                # Rough estimate for tool call overhead
                tool_str = f"{tool_call.name}({str(tool_call.arguments)})"
                total_chars += len(tool_str)
    
    return estimate_tokens_simple(str(total_chars), provider)


class SimpleTokenCounter:
    """
    Simple token counter that avoids heavy tokenizer dependencies.
    Follows Kode's lightweight approach.
    """
    
    def __init__(self, provider: str = "qwen"):
        self.provider = provider
        self.total_tokens_used = 0
        self.request_count = 0
    
    def count_from_usage(self, usage: Any) -> int:
        """Count tokens from LLM usage object."""
        if not usage:
            return 0
        
        total = (
            getattr(usage, 'input_tokens', 0) +
            getattr(usage, 'output_tokens', 0) +
            getattr(usage, 'cache_creation_input_tokens', 0) +
            getattr(usage, 'cache_read_input_tokens', 0)
        )
        
        self.total_tokens_used += total
        self.request_count += 1
        
        return total
    
    def estimate_from_text(self, text: str) -> int:
        """Estimate tokens from text."""
        return estimate_tokens_simple(text, self.provider)
    
    def estimate_from_messages(self, messages: List[LLMMessage]) -> int:
        """Estimate tokens from messages."""
        return estimate_tokens_from_messages(messages, self.provider)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get token usage statistics."""
        return {
            "total_tokens_used": self.total_tokens_used,
            "request_count": self.request_count,
            "avg_tokens_per_request": (
                self.total_tokens_used / max(self.request_count, 1)
            ),
            "provider": self.provider
        }
    
    def reset_stats(self):
        """Reset statistics."""
        self.total_tokens_used = 0
        self.request_count = 0


# Convenience functions for quick usage
def quick_token_count(messages: List[LLMMessage]) -> int:
    """Quick token count from messages - tries usage first, falls back to estimation."""
    # Try to get from usage info first (Kode approach)
    usage_count = count_tokens_from_messages(messages)
    if usage_count > 0:
        return usage_count
    
    # Fallback to estimation
    return estimate_tokens_from_messages(messages)


def quick_token_estimate(text: str, provider: str = "qwen") -> int:
    """Quick token estimation for text."""
    return estimate_tokens_simple(text, provider)


# Example usage comparison:
"""
# Heavy approach (like MemoryMonitor):
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-235B-A22B-Instruct-2507", 
                                         cache_dir="...", local_files_only=True)
tokens = len(tokenizer.encode(text))

# Lightweight approach (like Kode):
tokens = quick_token_estimate(text, "qwen")

# Or from messages with usage info:
tokens = quick_token_count(messages)
"""
