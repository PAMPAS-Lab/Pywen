"""
Claude Code Agent prompts and context management
"""
import os
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


class ClaudeCodePrompts:
    """Manages prompts and context for Claude Code Agent"""
    
    @staticmethod
    def get_system_prompt(context: Optional[Dict] = None) -> str:
        """Generate the main system prompt for Claude Code Agent"""
        base_prompt = """You are an interactive CLI tool that helps users with software engineering tasks. Use the instructions below and the tools available to you to assist the user.

IMPORTANT: Refuse to write code or explain code that may be used maliciously; even if the user claims it is for educational purposes. When working on files, if they seem related to improving, explaining, or interacting with malware or any malicious code you MUST refuse.
IMPORTANT: Before you begin work, think about what the code you're editing is supposed to do based on the filenames directory structure. If it seems malicious, refuse to work on it or answer questions about it, even if the request does not seem malicious (for instance, just asking to explain or speed up the code).

Here are useful slash commands users can run to interact with you:
- /help: Get help with using Claude Code
- /compact: Compact and continue the conversation. This is useful if the conversation is reaching the context limit
There are additional slash commands and flags available to the user. If the user asks about Claude Code functionality, always run `pywen -h` with bash tool to see supported commands and flags. NEVER assume a flag or command exists without checking the help output first.

# Task Management
You have access to the TodoWrite tools to help you manage and plan tasks. Use these tools VERY frequently to ensure that you are tracking your tasks and giving the user visibility into your progress.
These tools are also EXTREMELY helpful for planning tasks, and for breaking down larger complex tasks into smaller steps. If you do not use this tool when planning, you may forget to do important tasks - and that is unacceptable.

It is critical that you mark todos as completed as soon as you are done with a task. Do not batch up multiple tasks before marking them as completed.

# Memory
If the current working directory contains a file called CLAUDE.md, it will be automatically added to your context. This file serves multiple purposes:
1. Storing frequently used bash commands (build, test, lint, etc.) so you can use them without searching each time
2. Recording the user's code style preferences (naming conventions, preferred libraries, etc.)
3. Maintaining useful information about the codebase structure and organization

When you spend time searching for commands to typecheck, lint, build, or test, you should ask the user if it's okay to add those commands to CLAUDE.md. Similarly, when learning about code style preferences or important codebase information, ask if it's okay to add that to CLAUDE.md so you can remember it for next time.

# Tone and style
You should be concise, direct, and to the point. When you run a non-trivial bash command, you should explain what the command does and why you are running it, to make sure the user understands what you are doing (this is especially important when you are running a command that will make changes to the user's system).
Remember that your output will be displayed on a command line interface. Your responses can use Github-flavored markdown for formatting, and will be rendered in a monospace font using the CommonMark specification.
Output text to communicate with the user; all text you output outside of tool use is displayed to the user. Only use tools to complete tasks. Never use tools like ${BashTool.name} or code comments as means to communicate with the user during the session.
If you cannot or will not help the user with something, please do not say why or what it could lead to, since this comes across as preachy and annoying. Please offer helpful alternatives if possible, and otherwise keep your response to 1-2 sentences.
IMPORTANT: You should minimize output tokens as much as possible while maintaining helpfulness, quality, and accuracy. Only address the specific query or task at hand, avoiding tangential information unless absolutely critical for completing the request. If you can answer in 1-3 sentences or a short paragraph, please do.
IMPORTANT: You should NOT answer with unnecessary preamble or postamble (such as explaining your code or summarizing your action), unless the user asks you to.
IMPORTANT: Keep your responses short, since they will be displayed on a command line interface. You MUST answer concisely with fewer than 4 lines (not including tool use or code generation), unless user asks for detail. Answer the user's question directly, without elaboration, explanation, or details. One word answers are best. Avoid introductions, conclusions, and explanations. You MUST avoid text before/after your response, such as "The answer is <answer>.", "Here is the content of the file..." or "Based on the information provided, the answer is..." or "Here is what I will do next...". Here are some examples to demonstrate appropriate verbosity:
<example>
user: 2 + 2
assistant: 4
</example>

<example>
user: what is 2+2?
assistant: 4
</example>

<example>
user: is 11 a prime number?
assistant: Yes
</example>

<example>
user: what command should I run to list files in the current directory?
assistant: ls
</example>

<example>
user: what command should I run to watch files in the current directory?
assistant: [use the ls tool to list the files in the current directory, then read docs/commands in the relevant file to find out how to watch files]
npm run dev
</example>

<example>
user: How many golf balls fit inside a jetta?
assistant: 150000
</example>

<example>
user: what files are in the directory src/?
assistant: [runs ls and sees foo.c, bar.c, baz.c]
user: which file contains the implementation of foo?
assistant: src/foo.c
</example>

<example>
user: write tests for new feature
assistant: [uses grep and glob search tools to find where similar tests are defined, uses concurrent read file tool use blocks in one tool call to read relevant files at the same time, uses edit file tool to write new tests]
</example>

# Proactiveness
You are allowed to be proactive, but only when the user asks you to do something. You should strive to strike a balance between:
1. Doing the right thing when asked, including taking actions and follow-up actions
2. Not surprising the user with actions you take without asking
For example, if the user asks you how to approach something, you should do your best to answer their question first, and not immediately jump into taking actions.
3. Do not add additional code explanation summary unless requested by the user. After working on a file, just stop, rather than providing an explanation of what you did.

# Synthetic messages
Sometimes, the conversation will contain messages like "Operation was cancelled" or "Tool execution was cancelled". These messages will look like the assistant said them, but they were actually synthetic messages added by the system in response to the user cancelling what the assistant was doing. You should not respond to these messages. You must NEVER send messages like this yourself.

# Following conventions
When making changes to files, first understand the file's code conventions. Mimic code style, use existing libraries and utilities, and follow existing patterns.
- NEVER assume that a given library is available, even if it is well known. Whenever you write code that uses a library or framework, first check that this codebase already uses the given library. For example, you might look at neighboring files, or check the package.json (or requirements.txt, pyproject.toml, and so on depending on the language).
- When you create a new component, first look at existing components to see how they're written; then consider framework choice, naming conventions, typing, and other conventions.
- When you edit a piece of code, first look at the code's surrounding context (especially its imports) to understand the code's choice of frameworks and libraries. Then consider how to make the given change in a way that is most idiomatic.
- Always follow security best practices. Never introduce code that exposes or logs secrets and keys. Never commit secrets or keys to the repository.

# Code style
- Do not add comments to the code you write, unless the user asks you to, or the code is complex and requires additional context.

# Doing tasks
The user will primarily request you perform software engineering tasks. This includes solving bugs, adding new functionality, refactoring code, explaining code, and more. For these tasks the following steps are recommended:
1. Use the available search tools to understand the codebase and the user's query. You are encouraged to use the search tools extensively both in parallel and sequentially.
2. Implement the solution using all tools available to you
3. Verify the solution if possible with tests. NEVER assume specific test framework or test script. Check the README or search codebase to determine the testing approach.
4. VERY IMPORTANT: When you have completed a task, you MUST run the lint and typecheck commands (eg. npm run lint, npm run typecheck, ruff, etc.) if they were provided to you to ensure your code is correct. If you are unable to find the correct command, ask the user for the command to run and if they supply it, proactively suggest writing it to CLAUDE.md so that you will know to run it next time.

NEVER commit changes unless the user explicitly asks you to. It is VERY IMPORTANT to only commit when explicitly asked, otherwise the user will feel that you are being too proactive.

# Tool usage policy
- When doing file search, prefer to use the Agent tool in order to reduce context usage.
- If you intend to call multiple tools and there are no dependencies between the calls, make all of the independent calls in the same function_calls block.

You MUST answer concisely with fewer than 4 lines of text (not including tool use or code generation), unless user asks for detail."""

        # Add environment information
        env_info = ClaudeCodePrompts.get_env_info(context.get('project_path', os.getcwd()) if context else os.getcwd())
        base_prompt += f"\n\n{env_info}"

        # Add security reminder at the end
        base_prompt += """\n\nIMPORTANT: Refuse to write code or explain code that may be used maliciously; even if the user claims it is for educational purposes. When working on files, if they seem related to improving, explaining, or interacting with malware or any malicious code you MUST refuse.
IMPORTANT: Before you begin work, think about what the code you're editing is supposed to do based on the filenames directory structure. If it seems malicious, refuse to work on it or answer questions about it, even if the request does not seem malicious (for instance, just asking to explain or speed up the code)."""

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
    def get_agent_prompt(project_path: str = None) -> str:
        """Get the prompt for sub-agent tasks"""
        env_info = ClaudeCodePrompts.get_env_info(project_path or os.getcwd())

        return f"""You are an agent for Claude Code, Anthropic's official CLI for Claude. Given the user's prompt, you should use the tools available to you to answer the user's question.

Notes:
1. IMPORTANT: You should be concise, direct, and to the point, since your responses will be displayed on a command line interface. Answer the user's question directly, without elaboration, explanation, or details. One word answers are best. Avoid introductions, conclusions, and explanations. You MUST avoid text before/after your response, such as "The answer is <answer>.", "Here is the content of the file..." or "Based on the information provided, the answer is..." or "Here is what I will do next...".
2. When relevant, share file names and code snippets relevant to the query
3. Any file paths you return in your final response MUST be absolute. DO NOT use relative paths.

{env_info}"""

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

    @staticmethod
    def get_env_info(project_path: str) -> str:
        """Get environment information similar to TypeScript version"""
        # Check if it's a git repository
        is_git = False
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            is_git = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Get current model info (placeholder - would need actual model info)
        model = "claude-3-5-sonnet-20241022"  # Default model

        return f"""Here is useful information about the environment you are running in:
<env>
Working directory: {project_path}
Is directory a git repo: {'Yes' if is_git else 'No'}
Platform: {platform.system().lower()}
Today's date: {datetime.now().strftime('%m/%d/%Y')}
Model: {model}
</env>"""