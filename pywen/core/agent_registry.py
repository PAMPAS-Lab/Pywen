"""
Agent Registry - Manages current agent instance for tool access
"""
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pywen.agents.base_agent import BaseAgent


class AgentRegistry:
    """
    Registry to manage the current agent instance
    Allows tools to access the current agent for sub-agent functionality
    """
    
    def __init__(self):
        self._current_agent: Optional['BaseAgent'] = None
    
    def set_current_agent(self, agent: 'BaseAgent'):
        """Set the current active agent"""
        self._current_agent = agent
    
    def get_current_agent(self) -> Optional['BaseAgent']:
        """Get the current active agent"""
        return self._current_agent
    
    def clear_current_agent(self):
        """Clear the current agent"""
        self._current_agent = None


# Global agent registry instance
_agent_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry instance"""
    return _agent_registry


def set_current_agent(agent: 'BaseAgent'):
    """Set the current active agent globally"""
    _agent_registry.set_current_agent(agent)


def get_current_agent() -> Optional['BaseAgent']:
    """Get the current active agent globally"""
    return _agent_registry.get_current_agent()


def clear_current_agent():
    """Clear the current agent globally"""
    _agent_registry.clear_current_agent()
