"""
Context Manager for Claude Code Agent
Handles project context extraction and management
"""
import os
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ClaudeCodeContextManager:
    """
    Manages project context for Claude Code Agent
    Extracts Git info, directory structure, config files, etc.
    """
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self._context_cache: Optional[Dict[str, Any]] = None
        self._cache_valid = False
    
    def get_context(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get comprehensive project context
        
        Args:
            force_refresh: Force refresh of cached context
            
        Returns:
            Dictionary containing all context information
        """
        if not force_refresh and self._cache_valid and self._context_cache:
            return self._context_cache.copy()
        
        try:
            context = {
                'project_path': str(self.project_path),
            }
            
            # Add various context components
            context.update(self._get_git_context())
            context.update(self._get_directory_structure_context())
            context.update(self._get_claude_files_context())
            context.update(self._get_readme_context())
            context.update(self._get_code_style_context())
            context.update(self._get_package_context())
            
            # Cache the result
            self._context_cache = context
            self._cache_valid = True
            
            return context.copy()
            
        except Exception as e:
            logger.warning(f"Failed to build full context: {e}")
            # Fallback to minimal context
            return {'project_path': str(self.project_path)}
    
    def invalidate_cache(self):
        """Invalidate the context cache"""
        self._cache_valid = False
    
    def _get_git_context(self) -> Dict[str, str]:
        """Get Git repository information"""
        context = {}
        
        try:
            # Check if we're in a git repository
            result = subprocess.run(
                ['git', 'rev-parse', '--is-inside-work-tree'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                # Get current branch
                branch_result = subprocess.run(
                    ['git', 'branch', '--show-current'],
                    cwd=self.project_path,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if branch_result.returncode == 0:
                    context['git_branch'] = branch_result.stdout.strip()
                
                # Get git status
                status_result = subprocess.run(
                    ['git', 'status', '--porcelain'],
                    cwd=self.project_path,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if status_result.returncode == 0:
                    status = status_result.stdout.strip()
                    if status:
                        context['git_status'] = f"Modified files:\n{status}"
                    else:
                        context['git_status'] = "Working directory clean"
                
                # Get recent commits
                log_result = subprocess.run(
                    ['git', 'log', '--oneline', '-5'],
                    cwd=self.project_path,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if log_result.returncode == 0:
                    context['git_recent_commits'] = log_result.stdout.strip()
                    
        except Exception as e:
            logger.debug(f"Git context extraction failed: {e}")
        
        return context
    
    def _get_directory_structure_context(self) -> Dict[str, str]:
        """Get project directory structure"""
        context = {}
        
        try:
            # Get directory tree (limited depth to avoid huge output)
            tree_lines = []
            max_files = 100  # Limit to prevent huge context
            file_count = 0
            
            for root, dirs, files in os.walk(self.project_path):
                # Skip hidden directories and common ignore patterns
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {
                    'node_modules', '__pycache__', '.git', 'venv', 'env', 'dist', 'build'
                }]
                
                level = root.replace(str(self.project_path), '').count(os.sep)
                if level > 3:  # Limit depth
                    continue
                
                indent = '  ' * level
                tree_lines.append(f"{indent}{os.path.basename(root)}/")
                
                # Add files
                for file in sorted(files):
                    if file_count >= max_files:
                        tree_lines.append(f"{indent}  ... (truncated)")
                        break
                    
                    if not file.startswith('.') and not file.endswith(('.pyc', '.pyo')):
                        tree_lines.append(f"{indent}  {file}")
                        file_count += 1
                
                if file_count >= max_files:
                    break
            
            if tree_lines:
                context['directory_structure'] = '\n'.join(tree_lines[:50])  # Limit lines
                
        except Exception as e:
            logger.debug(f"Directory structure extraction failed: {e}")
        
        return context
    
    def _get_claude_files_context(self) -> Dict[str, str]:
        """Get CLAUDE.md and other Claude-specific files"""
        context = {}
        
        try:
            # Look for CLAUDE.md file
            claude_md_path = self.project_path / 'CLAUDE.md'
            if claude_md_path.exists():
                with open(claude_md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        context['claude_md'] = content[:5000]  # Limit size
            
            # Look for .clauderc or similar config files
            config_files = ['.clauderc', '.claude.json', 'claude.config.json']
            for config_file in config_files:
                config_path = self.project_path / config_file
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if content.strip():
                            context[f'claude_config_{config_file}'] = content[:1000]
                            
        except Exception as e:
            logger.debug(f"Claude files extraction failed: {e}")
        
        return context
    
    def _get_readme_context(self) -> Dict[str, str]:
        """Get README file information"""
        context = {}
        
        try:
            # Look for README files
            readme_files = ['README.md', 'README.rst', 'README.txt', 'README']
            for readme_file in readme_files:
                readme_path = self.project_path / readme_file
                if readme_path.exists():
                    with open(readme_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if content.strip():
                            context['readme'] = content[:3000]  # Limit size
                            break
                            
        except Exception as e:
            logger.debug(f"README extraction failed: {e}")
        
        return context
    
    def _get_code_style_context(self) -> Dict[str, str]:
        """Get code style and configuration information"""
        context = {}
        
        try:
            # Look for common config files
            config_files = {
                '.editorconfig': 'editor_config',
                '.prettierrc': 'prettier_config',
                '.eslintrc.json': 'eslint_config',
                'pyproject.toml': 'python_config',
                'setup.cfg': 'python_setup_config',
                'tslint.json': 'typescript_config',
                '.gitignore': 'gitignore'
            }
            
            for config_file, context_key in config_files.items():
                config_path = self.project_path / config_file
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if content.strip():
                            context[context_key] = content[:1000]  # Limit size
                            
        except Exception as e:
            logger.debug(f"Code style extraction failed: {e}")
        
        return context
    
    def _get_package_context(self) -> Dict[str, str]:
        """Get package and dependency information"""
        context = {}
        
        try:
            # Look for package files
            package_files = {
                'package.json': 'npm_package',
                'requirements.txt': 'python_requirements',
                'Pipfile': 'pipenv_config',
                'poetry.lock': 'poetry_lock',
                'Cargo.toml': 'rust_cargo',
                'go.mod': 'go_module',
                'composer.json': 'php_composer'
            }
            
            for package_file, context_key in package_files.items():
                package_path = self.project_path / package_file
                if package_path.exists():
                    with open(package_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if content.strip():
                            context[context_key] = content[:2000]  # Limit size
                            
        except Exception as e:
            logger.debug(f"Package context extraction failed: {e}")
        
        return context
