import asyncio
import aiohttp
import os
from typing import Dict, Any, List, Optional,Mapping
from dataclasses import dataclass
from .base_tool import BaseTool, ToolResult
from pywen.core.tool_registry2 import register_tool

CLAUDE_DESCRIPTION = """
- Allows Claude to search the web and use the results to inform responses
- Provides up-to-date information for current events and recent data
- Returns search result information formatted as search result blocks
- Use this tool for accessing information beyond Claude's knowledge cutoff
- Searches are performed automatically within a single API call
"""

@dataclass
class SearchResult:
    """Search result item."""
    title: str
    link: str
    snippet: str
    position: int = 0

@register_tool(name="web_search", providers=["claude", "qwen"])
class WebSearchTool(BaseTool):
    name="web_search"
    display_name="Web Search"
    description="Performs a web search using Serper API and returns the results. This tool is useful for finding current information on the internet."
    parameter_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find information on the web."
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of search results to return (default: 10, max: 20)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 20
                    }
                },
                "required": ["query"]
            }
    api_key = ""
    base_url = "https://google.serper.dev/search"
    
    def _get_api_key(self) -> str:
        """从配置或环境变量中获取 Serper API key"""
        # 1. 优先从配置文件中获取
        #if hasattr(self.config, 'serper_api_key') and self.config.serper_api_key:
            #return self.config.serper_api_key
        
        # 2. 从环境变量获取
        api_key = os.getenv("SERPER_API_KEY")
        if api_key:
            return api_key
        
        # 3. 如果都没有，返回空字符串
        return ""
    
    def validate_params(self, **kwargs) -> Optional[str]:
        """Validate the parameters for the WebSearchTool."""
        query = kwargs.get("query")
        num_results = kwargs.get("num_results", 10)
        
        if not query:
            return "The 'query' parameter is required."
        
        if not isinstance(query, str):
            return "The 'query' parameter must be a string."
        
        if not query.strip():
            return "The 'query' parameter cannot be empty."
        
        if not isinstance(num_results, int) or num_results < 1 or num_results > 20:
            return "The 'num_results' parameter must be an integer between 1 and 20."
        
        if not self.api_key:
            return "Serper API key is required. Set SERPER_API_KEY environment variable."
        
        return None
    
    def get_description(self, **kwargs) -> str:
        """Get description of the search operation."""
        query = kwargs.get("query", "")
        num_results = kwargs.get("num_results", 10)
        return f'Searching the web for: "{query}" (returning {num_results} results)'
    
    async def execute(self, **kwargs) -> ToolResult:
        """Perform web search using Serper API."""
        # Validate parameters
        validation_error = self.validate_params(**kwargs)
        if validation_error:
            return ToolResult(
                call_id=kwargs.get("call_id", ""),
                error=f"Invalid parameters provided. Reason: {validation_error}"
            )
        
        query = kwargs["query"]
        num_results = kwargs.get("num_results", 5)
        
        try:
            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json"
            }
            
            payload = {
                "q": query,
                "num": num_results,
                "gl": "us",
                "hl": "en"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        return ToolResult(
                            call_id=kwargs.get("call_id", ""),
                            error=f"Serper API error {response.status}: {error_text}"
                        )
                    
                    data = await response.json()
            
            search_results = self._parse_search_results(data)
            
            if not search_results:
                return ToolResult(
                    call_id=kwargs.get("call_id", ""),
                    result=f'No search results found for query: "{query}"'
                )
            
            formatted_results = self._format_search_results(query, search_results)
            
            return ToolResult(
                call_id=kwargs.get("call_id", ""),
                result=formatted_results,
                metadata={
                    "query": query,
                    "num_results": len(search_results),
                    "results": [
                        {
                            "title": result.title,
                            "url": result.link,
                            "snippet": result.snippet,
                            "position": result.position
                        }
                        for result in search_results
                    ]
                }
            )
            
        except asyncio.TimeoutError:
            return ToolResult(
                call_id=kwargs.get("call_id", ""),
                error=f"Search request timed out for query: {query}"
            )
        except Exception as e:
            error_message = f'Error during web search for query "{query}": {str(e)}'
            print(f"❌ {error_message}")
            return ToolResult(
                call_id=kwargs.get("call_id", ""),
                error=error_message
            )
    
    def _parse_search_results(self, data: Dict[str, Any]) -> List[SearchResult]:
        """Parse Serper API response into SearchResult objects."""
        results = []
        
        # Parse organic results
        organic_results = data.get("organic", [])
        for i, result in enumerate(organic_results):
            search_result = SearchResult(
                title=result.get("title", "No Title"),
                link=result.get("link", ""),
                snippet=result.get("snippet", "No description available"),
                position=i + 1
            )
            results.append(search_result)
        
        knowledge_graph = data.get("knowledgeGraph")
        if knowledge_graph:
            kg_result = SearchResult(
                title=f"Knowledge Graph: {knowledge_graph.get('title', 'Information')}",
                link=knowledge_graph.get("website", ""),
                snippet=knowledge_graph.get("description", "Knowledge graph information"),
                position=0
            )
            results.insert(0, kg_result)
        
        answer_box = data.get("answerBox")
        if answer_box:
            answer_result = SearchResult(
                title=f"Answer: {answer_box.get('title', 'Direct Answer')}",
                link=answer_box.get("link", ""),
                snippet=answer_box.get("answer", answer_box.get("snippet", "Direct answer")),
                position=0
            )
            results.insert(0, answer_result)
        
        return results
    
    def _format_search_results(self, query: str, results: List[SearchResult]) -> str:
        """Format search results into a readable string."""
        formatted = f'Web search results for "{query}":\n\n'
        for result in results:
            formatted += f"[{result.position}] {result.title}\n"
            formatted += f"🔗 {result.link}\n"
            formatted += f"📝 {result.snippet}\n\n"
        formatted += f"Found {len(results)} results for your search query."
        
        return formatted

    def build(self, provider:str = "", func_type: str = "") -> Mapping[str, Any]:
        if provider.lower() == "claude" or provider.lower() == "anthropic":
            res = {
                "name": self.name,
                "description": CLAUDE_DESCRIPTION,
                "input_schema": self.parameter_schema,
            }
        else:
            res = {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameter_schema
                }
            }
        return res
