"""
Token counting utilities - Python version of Kode's tokens.ts
Direct translation from TypeScript to Python
"""

from typing import Dict, List

from pywen.llm.llm_basics import LLMMessage

# Synthetic assistant messages that should be ignored for token counting
# This would be populated with messages that are system-generated
SYNTHETIC_ASSISTANT_MESSAGES = {
    "I'll help you with that.",
    "Let me analyze this for you.",
    "I understand your request.",
    # Add more synthetic messages as needed
}


def count_tokens(messages: List[LLMMessage]) -> int:
    """
    Count tokens from message history using the last assistant response's usage info.
    Direct Python translation of Kode's countTokens function.
    
    Args:
        messages: List of conversation messages
        
    Returns:
        Total token count from the most recent assistant message with usage info,
        or 0 if no usage info is found
    """
    i = len(messages) - 1
    
    while i >= 0:
        message = messages[i]
        
        # Check if this is an assistant message with usage info
        if (
            message.role == 'assistant' and
            hasattr(message, 'usage') and
            message.usage is not None
        ):
            # Check if this is not a synthetic assistant message
            # In Python, we need to handle the content structure differently
            is_synthetic = False
            
            if message.content:
                # Check if the content matches any synthetic messages
                content_text = message.content
                if isinstance(content_text, str):
                    is_synthetic = content_text in SYNTHETIC_ASSISTANT_MESSAGES
                elif isinstance(content_text, list) and len(content_text) > 0:
                    # Handle structured content (like Claude's format)
                    first_content = content_text[0]
                    if (
                        isinstance(first_content, dict) and 
                        first_content.get('type') == 'text' and
                        first_content.get('text') in SYNTHETIC_ASSISTANT_MESSAGES
                    ):
                        is_synthetic = True
            
            # If not synthetic, return the token count
            if not is_synthetic:
                usage = message.usage
                return (
                    usage.input_tokens +
                    getattr(usage, 'cache_creation_input_tokens', 0) +
                    getattr(usage, 'cache_read_input_tokens', 0) +
                    usage.output_tokens
                )
        
        i -= 1
    
    return 0


def count_cached_tokens(messages: List[LLMMessage]) -> int:
    """
    Count cached tokens from message history.
    Direct Python translation of Kode's countCachedTokens function.
    
    Args:
        messages: List of conversation messages
        
    Returns:
        Total cached token count from the most recent assistant message with usage info,
        or 0 if no usage info is found
    """
    i = len(messages) - 1
    
    while i >= 0:
        message = messages[i]
        
        # Check if this is an assistant message with usage info
        if (
            message.role == 'assistant' and
            hasattr(message, 'usage') and
            message.usage is not None
        ):
            usage = message.usage
            return (
                getattr(usage, 'cache_creation_input_tokens', 0) +
                getattr(usage, 'cache_read_input_tokens', 0)
            )
        
        i -= 1
    
    return 0


def get_token_usage_breakdown(messages: List[LLMMessage]) -> Dict[str, int]:
    """
    Get detailed token usage breakdown from the most recent assistant message.
    
    Args:
        messages: List of conversation messages
        
    Returns:
        Dictionary with detailed token breakdown
    """
    i = len(messages) - 1
    
    while i >= 0:
        message = messages[i]
        
        if (
            message.role == 'assistant' and
            hasattr(message, 'usage') and
            message.usage is not None
        ):
            usage = message.usage
            
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            cache_creation = getattr(usage, 'cache_creation_input_tokens', 0)
            cache_read = getattr(usage, 'cache_read_input_tokens', 0)
            
            return {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cache_creation_input_tokens': cache_creation,
                'cache_read_input_tokens': cache_read,
                'total_cached_tokens': cache_creation + cache_read,
                'total_tokens': input_tokens + output_tokens + cache_creation + cache_read,
                'non_cached_tokens': input_tokens + output_tokens
            }
        
        i -= 1
    
    return {
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_creation_input_tokens': 0,
        'cache_read_input_tokens': 0,
        'total_cached_tokens': 0,
        'total_tokens': 0,
        'non_cached_tokens': 0
    }


def add_synthetic_message(message: str) -> None:
    """
    Add a message to the synthetic messages set.
    
    Args:
        message: Message text to add to synthetic set
    """
    SYNTHETIC_ASSISTANT_MESSAGES.add(message)


def remove_synthetic_message(message: str) -> None:
    """
    Remove a message from the synthetic messages set.
    
    Args:
        message: Message text to remove from synthetic set
    """
    SYNTHETIC_ASSISTANT_MESSAGES.discard(message)


def is_synthetic_message(message: LLMMessage) -> bool:
    """
    Check if a message is synthetic (system-generated).
    
    Args:
        message: Message to check
        
    Returns:
        True if the message is synthetic, False otherwise
    """
    if not message.content:
        return False
    
    if isinstance(message.content, str):
        return message.content in SYNTHETIC_ASSISTANT_MESSAGES
    elif isinstance(message.content, list) and len(message.content) > 0:
        first_content = message.content[0]
        if (
            isinstance(first_content, dict) and 
            first_content.get('type') == 'text' and
            first_content.get('text') in SYNTHETIC_ASSISTANT_MESSAGES
        ):
            return True
    
    return False


# Convenience functions for backward compatibility
def quick_token_count(messages: List[LLMMessage]) -> int:
    """
    Quick token count - alias for count_tokens for backward compatibility.
    """
    return count_tokens(messages)


def quick_cached_token_count(messages: List[LLMMessage]) -> int:
    """
    Quick cached token count - alias for count_cached_tokens.
    """
    return count_cached_tokens(messages)


# Example usage:
"""
from pywen.utils.tokens import count_tokens, count_cached_tokens, get_token_usage_breakdown

# Count total tokens
total_tokens = count_tokens(conversation_messages)

# Count only cached tokens  
cached_tokens = count_cached_tokens(conversation_messages)

# Get detailed breakdown
breakdown = get_token_usage_breakdown(conversation_messages)
print(f"Total: {breakdown['total_tokens']}, Cached: {breakdown['total_cached_tokens']}")
"""
