"""
Claude Code Agent prompts and context management
"""
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


class ClaudeCodePrompts:
    """Manages prompts and context for Claude Code Agent"""
    
    @staticmethod
    def get_system_prompt(context: Optional[Dict] = None) -> str:
        """Generate the main system prompt for Claude Code Agent"""
        base_prompt = """You are Claude Code, an AI coding assistant created by Anthropic. You are an expert software engineer with deep knowledge of programming languages, software architecture, debugging, testing, and development workflows.

## Core Capabilities
- Code analysis, writing, and refactoring
- Debugging and troubleshooting
- Architecture design and code review
- File operations and project management
- Command execution and automation
- Documentation and explanation

## Interaction Guidelines
- Be concise and actionable in your responses
- Always provide complete, working code solutions
- Use appropriate tools to read, analyze, and modify files
- Execute commands when needed to test or build
- Explain your reasoning for complex decisions
- Ask for clarification when requirements are ambiguous

## Code Style & Best Practices
- Follow language-specific conventions and best practices
- Write clean, readable, and maintainable code
- Include appropriate error handling
- Add meaningful comments for complex logic
- Suggest improvements and optimizations when relevant

## Safety & Security
- Never execute destructive commands without explicit permission
- Validate file paths and prevent directory traversal
- Be cautious with system commands and file modifications
- Respect project structure and existing conventions"""

        if context:
            context_sections = []

            # Add project context
            if 'project_path' in context:
                context_sections.append(f"<context name=\"project_path\">\nCurrent project: {context['project_path']}\n</context>")

            # Add Git information
            if 'git_branch' in context:
                context_sections.append(f"<context name=\"git_branch\">\nCurrent branch: {context['git_branch']}\n</context>")

            if 'git_status' in context:
                context_sections.append(f"<context name=\"git_status\">\n{context['git_status']}\n</context>")

            if 'git_recent_commits' in context:
                context_sections.append(f"<context name=\"git_recent_commits\">\nRecent commits:\n{context['git_recent_commits']}\n</context>")

            # Add directory structure
            if 'directory_structure' in context:
                context_sections.append(f"<context name=\"directory_structure\">\nProject structure:\n{context['directory_structure']}\n</context>")

            # Add CLAUDE.md content if available
            if 'claude_md' in context:
                context_sections.append(f"<context name=\"project_memory\">\n{context['claude_md']}\n</context>")

            # Add README content
            if 'readme' in context:
                context_sections.append(f"<context name=\"readme\">\n{context['readme']}\n</context>")

            # Add package information
            if 'npm_package' in context:
                context_sections.append(f"<context name=\"npm_package\">\npackage.json:\n{context['npm_package']}\n</context>")

            if 'python_requirements' in context:
                context_sections.append(f"<context name=\"python_requirements\">\nrequirements.txt:\n{context['python_requirements']}\n</context>")

            # Add code style configs
            if 'editor_config' in context:
                context_sections.append(f"<context name=\"editor_config\">\n.editorconfig:\n{context['editor_config']}\n</context>")

            if 'prettier_config' in context:
                context_sections.append(f"<context name=\"prettier_config\">\n.prettierrc:\n{context['prettier_config']}\n</context>")

            # Add any other context items
            for key, value in context.items():
                if key not in {
                    'project_path', 'git_branch', 'git_status', 'git_recent_commits',
                    'directory_structure', 'claude_md', 'readme', 'npm_package',
                    'python_requirements', 'editor_config', 'prettier_config'
                } and value and isinstance(value, str):
                    context_sections.append(f"<context name=\"{key}\">\n{value}\n</context>")

            if context_sections:
                base_prompt += "\n\n" + "\n\n".join(context_sections)
        
        return base_prompt
    
    @staticmethod
    def get_agent_prompt() -> str:
        """Get the prompt for sub-agent tasks"""
        return """You are a focused sub-agent for Claude Code. Your role is to complete specific tasks efficiently and return concise results.

## Guidelines for Sub-Agent Tasks
- Be extremely concise and focused on the specific task
- Use tools efficiently and in parallel when possible
- Return absolute file paths when referencing files
- Provide structured, actionable results
- Avoid unnecessary explanations unless specifically requested
- Complete the task and return results quickly

## Tool Usage
- You can use multiple tools concurrently in a single response
- Focus on read-only operations when possible for analysis tasks
- Be precise with file operations and command execution"""

    @staticmethod
    def get_architect_prompt() -> str:
        """Get the prompt for architect/analysis tasks"""
        return """You are an architect sub-agent for Claude Code, specialized in code analysis and understanding.

## Your Role
- Analyze code structure and architecture
- Understand project organization and dependencies
- Provide insights about code quality and design patterns
- Help with refactoring and optimization suggestions

## Constraints
- Use only read-only tools (file reading, searching, listing)
- Focus on analysis rather than modification
- Provide clear, structured insights about the codebase
- Identify potential issues or improvement opportunities"""

    @staticmethod
    def build_context(project_path: str) -> Dict:
        """Build context information for the current project"""
        context = {
            'project_path': project_path,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # Get file tree
            context['file_tree'] = ClaudeCodePrompts._get_file_tree(project_path)
            
            # Get git status
            context['git_status'] = ClaudeCodePrompts._get_git_status(project_path)
            
            # Get CLAUDE.md content
            claude_md_path = os.path.join(project_path, 'CLAUDE.md')
            if os.path.exists(claude_md_path):
                with open(claude_md_path, 'r', encoding='utf-8') as f:
                    context['claude_md'] = f.read()
            
        except Exception as e:
            # Don't fail if context building has issues
            context['context_error'] = str(e)
        
        return context
    
    @staticmethod
    def _get_file_tree(project_path: str, max_depth: int = 3) -> str:
        """Generate a file tree for the project"""
        try:
            result = subprocess.run(
                ['tree', '-L', str(max_depth), '-I', '__pycache__|*.pyc|.git|node_modules'],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Fallback to manual tree generation
        return ClaudeCodePrompts._manual_file_tree(project_path, max_depth)
    
    @staticmethod
    def _manual_file_tree(path: str, max_depth: int, current_depth: int = 0) -> str:
        """Manual file tree generation as fallback"""
        if current_depth >= max_depth:
            return ""
        
        items = []
        try:
            for item in sorted(os.listdir(path)):
                if item.startswith('.') and item not in ['.gitignore', '.env.example']:
                    continue
                if item in ['__pycache__', 'node_modules', '.git']:
                    continue
                
                item_path = os.path.join(path, item)
                indent = "  " * current_depth
                
                if os.path.isdir(item_path):
                    items.append(f"{indent}{item}/")
                    if current_depth < max_depth - 1:
                        subtree = ClaudeCodePrompts._manual_file_tree(
                            item_path, max_depth, current_depth + 1
                        )
                        if subtree:
                            items.append(subtree)
                else:
                    items.append(f"{indent}{item}")
        except PermissionError:
            pass
        
        return "\n".join(items)
    
    @staticmethod
    def _get_git_status(project_path: str) -> str:
        """Get git status information"""
        try:
            # Check if it's a git repository
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                return "Not a git repository"
            
            # Get status
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                if result.stdout.strip():
                    return f"Git status:\n{result.stdout}"
                else:
                    return "Git status: clean working directory"
            
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        return "Git status unavailable"