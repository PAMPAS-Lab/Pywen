"""GitHub issue 报告命令实现"""
import aiohttp
import os
import sys
import platform
from typing import Dict, Any
from rich import get_console
from .base_command import BaseCommand, CommandResult, CommandAction

class BugCommand(BaseCommand):
    def __init__(self):
        super().__init__("bug", "create a GitHub issue for bug reports")
        self.console = get_console()
    
    async def execute(self, context: Dict[str, Any], args: str) ->  CommandResult:
        """创建 GitHub issue"""
        if not args.strip():
            self.console.print("[red]Usage: /bug <bug_description>[/red]")
            self.console.print("[dim]Example: /bug Found a memory leak in agent execution[/dim]")
            return  CommandResult(action=CommandAction.HANDLED, error="No bug description provided") 
        
        description = args.strip()
        
        # 检查 GitHub token
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            self.console.print("[red]❌ GITHUB_TOKEN environment variable not set[/red]")
            self.console.print("[dim]Please create a GitHub Personal Access Token with 'repo' scope:[/dim]")
            self.console.print("[dim]1. Go to https://github.com/settings/tokens/ [dim]")
            self.console.print("[dim]2. Generate new token with 'repo' permissions[/dim]")
            self.console.print("[dim]3. Set: export GITHUB_TOKEN=your_token[/dim]")
            return  CommandResult(action=CommandAction.HANDLED, error="GITHUB_TOKEN not set") 
        
        # 显示创建中状态
        self.console.print("[yellow]🔄 Creating GitHub issue...[/yellow]")
        
        try:
            issue_url = await self._create_github_issue(description, github_token)
            self.console.print(f"[green]✅ Issue created successfully: {issue_url}[/green]")
        except Exception as e:
            self.console.print(f"[red]❌ Failed to create issue: {str(e)}[/red]")
            self.console.print("[dim]Please ensure your GitHub token has 'repo' permissions[/dim]")
        
        return  CommandResult(action=CommandAction.HANDLED) 
    
    async def _create_github_issue(self, description: str, github_token: str) -> str:
        """使用 GitHub API 创建 issue"""
        # 先验证 token 和仓库访问权限
        repo_owner = "PAMPAS-Lab"
        repo_name = "Pywen"
        
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "Pywen-CLI"
        }
        
        # 先检查仓库是否存在和可访问
        repo_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        
        async with aiohttp.ClientSession() as session:
            # 验证仓库访问权限
            async with session.get(repo_url, headers=headers) as response:
                if response.status == 404:
                    raise Exception("Repository not found or no access permission")
                elif response.status == 401:
                    raise Exception("Invalid GitHub token or insufficient permissions")
                elif response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Repository access error ({response.status}): {error_text}")
            
            # 构建环境信息
            env_info = self._get_environment_info()
            
            issue_data = {
                "title": f"Bug Report: {description[:50]}{'...' if len(description) > 50 else ''}",
                "body": f"""## Bug Description
{description}

## Environment Information
{env_info}

---
_This issue was created automatically via Pywen `/bug` command._
""",
                "labels": ["bug", "pywen-report", "auto-generated"]
            }
            
            # 创建 issue
            issues_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues"
            async with session.post(issues_url, headers=headers, json=issue_data) as response:
                if response.status == 201:
                    result = await response.json()
                    return result["html_url"]
                else:
                    error_text = await response.text()
                    raise Exception(f"GitHub API error ({response.status}): {error_text}")
    
    def _get_environment_info(self) -> str:
        """获取环境信息"""
        try:
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            platform_info = platform.platform()
            architecture = platform.machine()
            
            return f"""- **Pywen Version**: 1.0.0
- **Python Version**: {python_version}
- **Platform**: {platform_info}
- **Architecture**: {architecture}"""
        except Exception:
            return "- **Environment**: Unable to detect"
