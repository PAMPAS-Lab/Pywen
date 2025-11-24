"""
Tool Adapter - Adapts Pywen tools for Claude Code context
Implements the Adapter Pattern to provide different descriptions for tools
when used in Claude Code context while preserving original tool descriptions.
"""

from typing import Any, Dict, Optional
from pywen.tools.base import BaseTool


class ClaudeCodeToolAdapter(BaseTool):
    """
    Adapter that wraps a Pywen tool and provides Claude Code specific descriptions
    while preserving the original tool's functionality and original description.
    
    This implements the Adapter Pattern to allow the same tool to have different
    descriptions in different contexts (Pywen vs Claude Code).
    """
    
    def __init__(self, original_tool: BaseTool, claude_code_description: str):
        """
        Initialize the adapter with the original tool and Claude Code specific description.
        
        Args:
            original_tool: The original Pywen tool to adapt
            claude_code_description: The description to use in Claude Code context
        """
        # Initialize with Claude Code specific description
        super().__init__(
            name=original_tool.name,
            display_name=original_tool.display_name,
            description=claude_code_description,  # Use Claude Code description
            parameter_schema=original_tool.parameter_schema,
            is_output_markdown=original_tool.is_output_markdown,
            can_update_output=original_tool.can_update_output,
            config=original_tool.config,
            risk_level=original_tool.risk_level
        )
        
        # Store reference to original tool
        self._original_tool = original_tool
        self._original_description = original_tool.description
        self._claude_code_description = claude_code_description
    
    @property
    def original_description(self) -> str:
        """Get the original Pywen tool description."""
        return self._original_description
    
    @property
    def claude_code_description(self) -> str:
        """Get the Claude Code specific description."""
        return self._claude_code_description
    
    def get_function_declaration(self) -> Dict[str, Any]:
        """
        Override to return Claude Code specific description in function declaration.
        This is what gets sent to the LLM.
        """
        return {
            "name": self.name,
            "description": self._claude_code_description,  # Use Claude Code description for LLM
            "parameters": self.parameter_schema
        }
    
    def is_risky(self, **kwargs) -> bool:
        """Delegate to original tool."""
        return self._original_tool.is_risky(**kwargs)
    
    async def execute(self, **kwargs):
        """Delegate execution to original tool."""
        return await self._original_tool.execute(**kwargs)
    
    def __getattr__(self, name):
        """
        Delegate any other attribute access to the original tool.
        This ensures full compatibility with the original tool's interface.
        """
        return getattr(self._original_tool, name)


class ToolAdapterFactory:
    """
    Factory class to create Claude Code tool adapters with predefined descriptions.
    This centralizes the mapping between tools and their Claude Code descriptions.
    """
    
    # Mapping of tool names to their Claude Code descriptions
    CLAUDE_CODE_DESCRIPTIONS = {

        # Common file tools with detailed Claude Code descriptions
        "write_file": """Writes a file to the local filesystem.

Usage:
- This tool will overwrite the existing file if there is one at the provided path.
- If this is an existing file, you MUST use the Read tool first to read the file's contents. This tool will fail if you did not read the file first.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
- Only use emojis if the user explicitly requests it. Avoid writing emojis to files unless asked.""",

        "read_file": """Reads a file from the local filesystem. You can access any file directly by using this tool.

Assume this tool is able to read all files on the machine. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- By default, it reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters
- Any lines longer than 2000 characters will be truncated
- Results are returned using cat -n format, with line numbers starting at 1
- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful.
- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.""",

        "edit": """Performs exact string replacements in files.

Usage:
- You must use your `Read` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file.
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.""",

        # Command execution tools
        "bash": """Executes a given bash command in a persistent shell session with optional timeout, ensuring proper handling and security measures.

Before executing the command, please follow these steps:

1. Directory Verification:
   - If the command will create new directories or files, first use the LS tool to verify the parent directory exists and is the correct location
   - For example, before running "mkdir foo/bar", first use LS to check that "foo" exists and is the intended parent directory

2. Command Execution:
   - Always quote file paths that contain spaces with double quotes (e.g., cd "path with spaces/file.txt")
   - Examples of proper quoting:
     - cd "/Users/name/My Documents" (correct)
     - cd /Users/name/My Documents (incorrect - will fail)
     - python "/path/with spaces/script.py" (correct)
     - python /path/with spaces/script.py (incorrect - will fail)
   - After ensuring proper quoting, execute the command.
   - Capture the output of the command.

Usage notes:
  - The command argument is required.
  - You can specify an optional timeout in milliseconds (up to 600000ms / 10 minutes). If not specified, commands will timeout after 120000ms (2 minutes).
  - It is very helpful if you write a clear, concise description of what this command does in 5-10 words.
  - If the output exceeds 30000 characters, output will be truncated before being returned to you.
  - You can use the `run_in_background` parameter to run the command in the background, which allows you to continue working while the command runs. You can monitor the output using the Bash tool as it becomes available. Never use `run_in_background` to run 'sleep' as it will return immediately. You do not need to use '&' at the end of the command when using this parameter.
  - VERY IMPORTANT: You MUST avoid using search commands like `find` and `grep`. Instead use Grep, Glob, or Task to search. You MUST avoid read tools like `cat`, `head`, `tail`, and `ls`, and use Read and LS to read files.
 - If you _still_ need to run `grep`, STOP. ALWAYS USE ripgrep at `rg` first, which all Claude Code users have pre-installed.
  - When issuing multiple commands, use the ';' or '&&' operator to separate them. DO NOT use newlines (newlines are ok in quoted strings).
  - Try to maintain your current working directory throughout the session by using absolute paths and avoiding usage of `cd`. You may use `cd` if the User explicitly requests it.""",

        # Directory and file exploration tools
        "ls": "Lists files and directories in a given path. The path parameter must be an absolute path, not a relative path. You can optionally provide an array of glob patterns to ignore with the ignore parameter. You should generally prefer the Glob and Grep tools, if you know which directories to search.",

        "grep": """A powerful search tool built on ripgrep

Usage:
- ALWAYS use Grep for search tasks. NEVER invoke `grep` or `rg` as a Bash command. The Grep tool has been optimized for correct permissions and access.
- Supports full regex syntax (e.g., "log.*Error", "function\\s+\\w+")
- Filter files with glob parameter (e.g., "*.js", "**/*.tsx") or type parameter (e.g., "js", "py", "rust")""",

        "glob": """- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns
- When you are doing an open ended search that may require multiple rounds of globbing and grepping, use the Agent tool instead
- You have the capability to call multiple tools in a single response. It is always better to speculatively perform multiple searches as a batch that are potentially useful.""",

        # Web tools
        "web_fetch": """- Fetches content from a specified URL and processes it using an AI model
- Takes a URL and a prompt as input
- Fetches the URL content, converts HTML to markdown
- Processes the content with the prompt using a small, fast model
- Returns the model's response about the content
- Use this tool when you need to retrieve and analyze web content""",

        "web_search": """- Allows Claude to search the web and use the results to inform responses
- Provides up-to-date information for current events and recent data
- Returns search result information formatted as search result blocks
- Use this tool for accessing information beyond Claude's knowledge cutoff
- Searches are performed automatically within a single API call"""
    }
    
    @classmethod
    def create_adapter(cls, original_tool: BaseTool) -> ClaudeCodeToolAdapter:
        """
        Create a Claude Code adapter for the given tool.
        
        Args:
            original_tool: The original Pywen tool to adapt
            
        Returns:
            ClaudeCodeToolAdapter: Adapter with Claude Code specific description
            
        Raises:
            ValueError: If no Claude Code description is defined for the tool
        """
        claude_code_description = cls.CLAUDE_CODE_DESCRIPTIONS.get(original_tool.name)
        
        if claude_code_description is None:
            raise ValueError(f"No Claude Code description defined for tool: {original_tool.name}")
        
        return ClaudeCodeToolAdapter(original_tool, claude_code_description)
    
    @classmethod
    def create_adapters(cls, original_tools: list[BaseTool]) -> list[ClaudeCodeToolAdapter]:
        """
        Create Claude Code adapters for a list of tools.
        
        Args:
            original_tools: List of original Pywen tools to adapt
            
        Returns:
            List of ClaudeCodeToolAdapter instances
        """
        adapters = []
        for tool in original_tools:
            try:
                adapter = cls.create_adapter(tool)
                adapters.append(adapter)
            except ValueError:
                # If no Claude Code description is defined, use the original tool
                adapters.append(tool)
        
        return adapters

    @classmethod
    def add_description(cls, tool_name: str, description: str):
        """
        Add or update a Claude Code description for a tool.

        Args:
            tool_name: Name of the tool
            description: Claude Code specific description
        """
        cls.CLAUDE_CODE_DESCRIPTIONS[tool_name] = description
