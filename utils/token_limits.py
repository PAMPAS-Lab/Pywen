"""Token limit management utilities."""

import sys
from pathlib import Path
from typing import Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.config import ModelProvider


class TokenLimits:
    """Token limit management for different models."""
    
    # Model token limits
    MODEL_LIMITS = {
        ModelProvider.QWEN: {
            "qwen-coder-plus": 32768,
            "qwen-coder": 8192,
            "qwen-turbo": 8192,
        },
        ModelProvider.OPENAI: {
            "gpt-4": 8192,
            "gpt-3.5-turbo": 4096,
        }
    }
    
    @classmethod
    def get_limit(cls, provider: ModelProvider, model: str) -> int:
        """Get token limit for a specific model."""
        provider_limits = cls.MODEL_LIMITS.get(provider, {})
        return provider_limits.get(model, 4096)  # Default fallback
    
    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """Rough estimation of token count."""
        # Simple approximation: ~4 characters per token
        return len(text) // 4
    
    @classmethod
    def should_compress(cls, current_tokens: int, limit: int, threshold: float = 0.8) -> bool:
        """Check if conversation should be compressed."""
        return current_tokens > (limit * threshold)
