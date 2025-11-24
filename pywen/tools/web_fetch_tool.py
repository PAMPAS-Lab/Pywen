import asyncio
import aiohttp
import html
import re
from typing import Any, Mapping
from .base_tool import BaseTool, ToolResult
from pywen.core.tool_registry2 import register_tool

CLAUDE_DESCRIPTION = """
- Fetches content from a specified URL and processes it using an AI model
- Takes a URL and a prompt as input
- Fetches the URL content, converts HTML to markdown
- Processes the content with the prompt using a small, fast model
- Returns the model's response about the content
- Use this tool when you need to retrieve and analyze web content
"""

@register_tool(name="web_fetch", providers=["claude", "qwen"])
class WebFetchTool(BaseTool):
    name="web_fetch"
    display_name="Fetch Web Content"
    description="Fetch content from web URLs"
    parameter_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch content from"
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds (default: 30)",
                "default": 30
            }
        },
        "required": ["url"]
    }
    
    def _clean_html_content(self, html_content: str) -> str:
        """Extract clean text from HTML content using built-in modules."""
        try:
            # 移除脚本和样式标签及其内容
            html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            
            # 移除其他不需要的标签
            unwanted_tags = ['nav', 'header', 'footer', 'aside', 'form', 'button']
            for tag in unwanted_tags:
                html_content = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            
            # 移除所有HTML标签
            text = re.sub(r'<[^>]+>', '', html_content)
            
            # 解码HTML实体
            text = html.unescape(text)
            
            # 清理空白字符
            text = re.sub(r'\s+', ' ', text)  # 多个空白字符替换为单个空格
            text = re.sub(r'\n\s*\n', '\n', text)  # 多个换行替换为单个换行
            text = text.strip()
            
            # 移除过多的重复字符
            text = re.sub(r'(.)\1{3,}', r'\1\1', text)  # 超过3个重复字符减少到2个
            
            return text
            
        except Exception as e:
            # 简单的后备方案
            text = re.sub(r'<[^>]+>', '', html_content)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 5000:
                text = text[:5000] + "...[内容已截断]"
            return text

    async def execute(self, **kwargs) -> ToolResult:
        """Fetch web content and extract clean text."""
        url = kwargs.get("url")
        timeout = kwargs.get("timeout", 30)
        
        if not url:
            return ToolResult(call_id="", error="No URL provided")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                    if response.status == 200:
                        html_content = await response.text()
                        clean_text = self._clean_html_content(html_content)
                        return ToolResult(
                            call_id="",
                            result=f"Content from {url}:\n\n{clean_text}"
                        )
                    elif response.status == 403:
                        return ToolResult(
                            call_id="",
                            error=f"Access denied (403) for {url}. Website may have anti-bot protection."
                        )
                    else:
                        return ToolResult(
                            call_id="",
                            error=f"HTTP {response.status}: Failed to fetch {url}"
                        )
        
        except asyncio.TimeoutError:
            return ToolResult(call_id="", error=f"Timeout fetching {url}")
        except Exception as e:
            return ToolResult(call_id="", error=f"Error fetching {url}: {str(e)}")

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
