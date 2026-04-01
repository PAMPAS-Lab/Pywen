# Pywen

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![Python 3.12-](https://img.shields.io/badge/python-3.12-red.svg)](https://www.python.org/downloads/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Alpha](https://img.shields.io/badge/Status-Alpha-red)

[**中文版**](README_ch.md) | **English**

![Pywen Logo](./docs/Pywen.png)

**Pywen** is a full-stack Python Code Agent platform built for transparent engineering practice and reproducible research. It serves both as a practical coding assistant for developers and as a unified foundation where different agents can be compared, debugged, and evolved in a controllable environment.

## 🎯 Project Positioning

Pywen is positioned as a unified foundation for the Code Agent ecosystem, with two complementary roles:

- **Fair Arena (Research)**: Reproducible and comparable evaluation environment for different Code Agents
- **Agent OS (Engineering)**: Stable and evolvable runtime for moving from prototype to production

Core design goals:

- **Reproducibility**: Reconstruct diverse agent behaviors under one Python framework
- **Fair Comparison**: Standardized tool interfaces and evaluation workflows
- **Iterative Stability**: Modular architecture for smooth model/tool evolution
- **Production Readiness**: Permission control, approval flow, and trajectory audit for governance

## 🧬 Recent Updates

- 2026.01.25: Launched the **Skills system** for reusable capability injection and modular extension. Post: https://mp.weixin.qq.com/s/8t6JtpT9ARB7hy3fow6xkA
- 2025.12.29: Released **Pywen 2.0** with a core refactor focused on maintainability and extensibility. Post: https://mp.weixin.qq.com/s/U1XBBNLGWObU5MOdTZcECQ
- 2025.11.26: Refactored core agent naming from QwenAgent to PywenAgent for better clarity and consistency
- 2025.08.26: Updated the `/agent` module by adding the Claude Code agent, with execution logic aligned to Claude Code, and introducing dedicated tools such as the task tool and todowrite tool. You can switch to the Claude Code agent using `/agent claude`.
- 2025.08.08: Updated the `/agent` switch agent module, added DeepResearch agent, with execution logic aligned with Google's open-source DeepResearch LangGraph version. You can use `/agent research` to switch GeminiResearchDemo agent. Before you use it, please make sure you have the serper api key.
- 2025.08.06: Released the first version of Pywen, with execution logic aligned with Gemini CLI/Qwen Code

## 🎯 Project Background

Pywen was developed in response to common pain points in existing Code Agent tooling for Python users: fragmented tech stacks, limited observability, difficult customization, and poor cross-agent comparability.

From implementation perspective, Pywen references and learns from projects such as [**Qwen-Code**](https://github.com/QwenLM/qwen-code) and [**Codex**](https://github.com/openai/codex), and can run with code-capable models including [**Qwen3-Coder**](https://github.com/QwenLM/Qwen3-Coder). We acknowledge and appreciate these open-source contributions. These are development choices rather than the primary product positioning.

### Model Choice (Example: Qwen3-Coder)

- 🚀 **Code Specialization**: Qwen3-Coder excels in code generation, understanding, and debugging
- ⚡ **Efficient Inference**: Optimized model architecture providing fast responses
- 🔧 **Engineering Practicality**: Specifically trained for real-world software development scenarios

**Project Status:** The project is still under active development. We welcome your help in improving Pywen.

## Differences from Other Code Agent CLIs

Pywen is a Python-native CLI with strong ecosystem compatibility and a transparent modular architecture. It is designed for both practical delivery and scientific iteration: developers can inspect and control execution paths, while researchers can run fair comparisons and reproducible studies in a unified environment. This research-friendly and engineering-oriented design helps build an open, evolvable foundation for the Code Agent community.

## ✨ Features

- 🤖 **Multi-Agent Support**: Pywen Agent (Qwen3-Coder based), Claude Code Agent, Codex Agent, and Research Agent
- 🚀 **Multi-Model Support**: Supports Qwen as well as OpenAI- and Anthropic-compatible APIs, enabling seamless switching between different models
- 📦 **Modular**: Built on modular architecture, extensible and customizable
- 🛠️ **Rich Tool Ecosystem**: File editing, bash execution, web search, memory management, and more
- 📊 **Trajectory Recording**: Detailed logging of all Agent operations for debugging and analysis
- ⚙️ **Smart Configuration**: YAML-based configuration with environment variable support
- 📈 **Session Statistics**: Real-time tracking of API calls, tool usage, and token consumption
- 🔄 **Agent Switching**: Seamlessly switch between different agents using `/agent` command

## 🚀 Quick Start

### Installation

```bash 
pip install pywen
```

<details>
<summary>Build from source with uv (recommended)</summary>

```bash
git clone https://github.com/PAMPAS-Lab/Pywen.git
cd Pywen
uv venv
uv sync --all-extras

# linux/macos
source .venv/bin/activate

# windows
.venv\Scripts\activate
```

</details>

### First Use

Simply run the `pywen` command to start:

```bash
# Interactive mode (default)
pywen

# Single prompt mode
pywen "Create a Python hello world script"

# Specify agent type
pywen --agent pywen
pywen --agent claude
pywen --agent codex

# Specify model and API key via command line
pywen --model "Qwen/Qwen3-Coder-Plus" --api_key "your-key"
```

If it's your first run and there's no configuration file:

- Pywen will first try to locate a config file:
  - Default path: `~/.pywen/pywen_config.yaml`
  - A `pywen_config.yaml` in the current working directory or any parent directory
- If none is found, it will try to locate an example config `pywen_config.example.yaml` and copy it to the default path:

```bash
# built-in example configuration located at `pywen/config/pywen_config.example.yaml`
cp pywen/config/pywen_config.example.yaml ~/.pywen/pywen_config.yaml
```
- If there is neither a real config file nor an example file, Pywen will exit with an error message and suggest two options:
  - Manually copy an example file to `pywen_config.yaml` and edit fields like `api_key` / `model`
  - Or provide configuration via environment variables (e.g. `PYWEN_API_KEY`, `PYWEN_MODEL`, `PYWEN_BASE_URL`)

Therefore, the **recommended workflow** is to prepare `pywen_config.yaml` (or the relevant environment variables) according to the example configuration before running `pywen`.

### Basic Usage

Once you enter the Pywen command-line interface, you can:

```bash
# File operations
> Create a Python script to calculate Fibonacci sequence
> Refactor functions in main.py to make them more efficient

# Code analysis and debugging
> Fix bugs in this project and add unit tests
> Analyze performance bottlenecks in my code

# Project management
> Create a new Flask web application with proper structure
> Add comprehensive documentation to this codebase
```

## 📖 User Guide

### Command Line Interface

#### Available Commands

```bash
# System commands
/about       show version info
/agent       switch between different agents (pywen/claude/codex/research)
/clear       clear the screen and conversation history
/help        for help on pywen code
/model       view and manage model configurations
/stats       check session stats
/tools       list available Pywen tools 
/bug         submit a bug report
/quit        exit the cli

# Special commands
!<command>   - Execute shell command

# Keyboard shortcuts
Ctrl+Y       - Toggle YOLO mode (auto-approve all operations - use with caution!)

# Direct input of task descriptions to execute agent
```

#### Agent Switching

Pywen supports multiple specialized agents:

```bash
# List available agents
/agent

# Switch to Pywen Agent (default, Qwen3-Coder based)
/agent pywen

# Switch to Claude Code Agent
/agent claude

# Switch to Codex Agent (OpenAI GPT-5 Codex)
/agent codex

# Switch to Research Agent (Gemini-based)
/agent research
```

**Available Agents:**
- **Pywen Agent** (`pywen`): General-purpose coding assistant based on Qwen3-Coder
- **Claude Code Agent** (`claude`): Advanced file operations and project understanding
- **Codex Agent** (`codex`): OpenAI Codex-based coding assistant
- **Research Agent** (`research`): Multi-step research agent for comprehensive information gathering

### YOLO Mode

**Use with caution:**
- Press `Ctrl+Y` to toggle YOLO mode
- **Default behavior**: All tool calls require user confirmation for safety
- In YOLO mode, all tool calls are automatically approved without user confirmation
- This speeds up execution but removes safety checks
- Mode status is displayed in the interface
- You can also type 'a' (always) when prompted for tool confirmation to enable YOLO mode

### Configuration Management

Pywen uses YAML configuration files. The default configuration file is located at `~/.pywen/pywen_config.yaml`.

**Example Configuration:**

```yaml
# Default agent to use
default_agent: pywen

# Model configurations
agents:
  # Pywen Agent (Qwen3-Coder)
  - agent_name: pywen
    model: "Qwen/Qwen3-Coder-Plus"
    api_key: "your-api-key"
    base_url: "https://api-inference.modelscope.cn/v1"
    provider: openai
    wire_api: chat

  # Claude Code Agent
  - agent_name: claude
    provider: anthropic
    model: "claude-3.5-sonnet"
    api_key: "your-anthropic-key"
    base_url: "https://api.anthropic.com/v1"
    wire_api: chat

  # Codex Agent
  - agent_name: codex
    provider: openai
    model: "gpt-5.1"
    api_key: "your-openai-key"
    base_url: "https://api.openai.com/v1/"
    wire_api: responses

# Permission level: locked / edit_only / planning / yolo
permission_level: locked

# Maximum conversation turns
max_turns: 10

# Memory monitor settings
memory_monitor:
  check_interval: 3
  maximum_capacity: 100000
  model: "Qwen/Qwen3-235B-A22B-Instruct-2507"
```

**Configuration Priority:**
1. Command line arguments (highest)
2. Configuration file values
3. Environment variables
4. Default values (lowest)

**Configuration File Location:**
Pywen ships an embedded example configuration; on first run it will copy it to the default config path.
- Default: `~/.pywen/pywen_config.yaml`
- You can specify a custom path with `--config` flag

### Environment Variables

You can set API keys through environment variables. Pywen supports agent-specific environment variables:

```bash
# Pywen Agent (Qwen3-Coder)
export PYWEN_PYWEN_API_KEY="your-api-key"
export PYWEN_PYWEN_BASE_URL="https://api-inference.modelscope.cn/v1"
export PYWEN_PYWEN_MODEL="Qwen/Qwen3-Coder-Plus"

# Claude Agent
export PYWEN_CLAUDE_API_KEY="your-anthropic-key"
export PYWEN_CLAUDE_BASE_URL="https://api.anthropic.com/v1"
export PYWEN_CLAUDE_MODEL="claude-3.5-sonnet"

# Codex Agent
export PYWEN_CODEX_API_KEY="your-openai-key"
export PYWEN_CODEX_BASE_URL="https://api.openai.com/v1/"
export PYWEN_CODEX_MODEL="gpt-5.1"

# Generic fallback (if agent-specific not set)
export PYWEN_API_KEY="your-api-key"
export PYWEN_BASE_URL="https://api-inference.modelscope.cn/v1"

# Tool API Keys (optional but recommended)
export SERPER_API_KEY="your-serper-api-key"  # For web search
export JINA_API_KEY="your-jina-api-key"      # For content reading
```

**Environment Variable Format:**
- Agent-specific: `PYWEN_<AGENT_NAME>_<FIELD>` (e.g., `PYWEN_PYWEN_API_KEY`)
- Generic: `PYWEN_<FIELD>` (fallback if agent-specific not set)

### Getting API Keys

**Serper API (Web Search):**
1. Visit [serper.dev](https://serper.dev/)
2. Sign up for a free account
3. Get your API key from the dashboard

**Jina API (Content Reading):**
1. Visit [jina.ai](https://jina.ai/)
2. Sign up for a free account
3. Get your API key from the dashboard

## 🛠️ Available Tools

Pywen provides a comprehensive toolkit for software development. Different agents may have access to different tools:

**Common Tools (Available to most agents):**
- **File Operations**: `read_file`, `write_file`, `edit`, `read_many_files`
- **File System**: `ls`, `glob`, `grep`
- **Bash Execution**: `bash` - Run shell commands and scripts
- **Web Operations**: `web_search`, `web_fetch`
- **Memory Management**: `memory` - Store and retrieve information

**Agent-Specific Tools:**
- **Claude Agent**: `task`, `todo` - Task planning and management
- **Codex Agent**: `update_plan`, `apply_patch` - Codex-specific operations
- **Research Agent**: Specialized research workflow tools

For detailed information about all available tools and their capabilities, see [docs/tools.md](docs/tools.md).

## 🔌 MCP (Model Context Protocol) Integration

Pywen also supports **MCP (Model Context Protocol)** to connect external tools and services such as playwright.

### Enabling MCP
1. Open your configuration file:
   ```bash
   ~/.pywen/pywen_config.yaml
   ```
2. Locate the `mcp` section and enable it:
   ```yaml
   mcp:
     enabled: true
     isolated: false
     servers:
       - name: "playwright"
         command: "npx"
         args:
           - "@playwright/mcp@latest"
         enabled: true
         include:
           - "browser_*"
         save_images_dir: "./outputs/playwright"
   ```
### Node.js 
Ensure that you have Node.js installed. You can verify it with the following command:

```bash
node -v
```
If you don’t have it installed, please follow the [Node.js installation guide](https://nodejs.org/).

### Browser Dependency
If your device does not have a browser installed, install browser for Playwright with:

```bash
npx playwright install --with-deps
```

After enabling MCP and installing the required browser, Pywen will be able to call the `playwright` MCP server for tasks like browser automation, screenshot capture, and web interaction.

## 📊 Trajectory Recording

Pywen automatically records detailed execution trajectories for debugging and analysis:

```bash
# Trajectory files are automatically saved to trajectories/ directory
trajectories/trajectory_xxxxxx.json
```

Trajectory files contain:
- **LLM Interactions**: All messages, responses, and tool calls
- **Agent Steps**: State transitions and decision points
- **Tool Usage**: Which tools were called and their results
- **Metadata**: Timestamps, token usage, and execution metrics

## 📈 Session Statistics

Monitor your usage with real-time statistics:

```bash
> /stats
```

Tracks:
- API calls and token consumption
- Tool usage patterns
- Session duration
- Model performance metrics

## 🤝 Contributing

We welcome contributions to Pywen! Here's how to get started:

1. Fork the repository
2. Set up the development environment:
   ```bash
   git clone https://github.com/your-username/Pywen.git
   cd Pywen
   uv venv
   uv sync --all-extras

   # linux/macos
   source .venv/bin/activate

   # windows
   .venv\Scripts\activate
   ```
3. Create a feature branch
4. Make your changes and add tests
5. Submit a pull request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add tests for new features
- Update documentation as needed
- Use type hints appropriately
- Ensure all tests pass before submitting

## 📋 Requirements

- Python 3.10+,<3.13
- API key for your chosen agent:
  - **Pywen Agent**: ModelScope API key or Qwen API key
  - **Claude Agent**: Anthropic API key
  - **Codex Agent**: OpenAI API key
  - **Research Agent**: Google API key (and Serper API key for web search)
- Internet connection for API access
- (Optional) Node.js for MCP server support

## 🔧 Troubleshooting

### Common Issues

**Configuration Issues:**
```bash
# re-create config from the built-in example template
rm ~/.pywen/pywen_config.yaml
pywen
```

**API Key Issues:**
```bash
# Verify your API key is set (for Pywen agent)
echo $PYWEN_PYWEN_API_KEY

# Or check generic fallback
echo $PYWEN_API_KEY

# Check configuration in Pywen
> /model
```

**Agent Switching Issues:**
```bash
# List available agents
> /agent

# Check current agent type
> /stats
```

## 🙏 Acknowledgments

We thank:

- **Google** for the [Gemini CLI](https://github.com/google-gemini/gemini-cli) project, which provided agent execution logic and rich tool ecosystem libraries for this project
- **Alibaba Cloud Qwen Team** for providing the powerful [Qwen3-Coder](https://github.com/QwenLM/Qwen3-Coder) model and [Qwen-Code](https://github.com/QwenLM/qwen-code) reference implementation
- **ByteDance** for the [trae-agent](https://github.com/bytedance/trae-agent) project, which provided valuable foundational architecture for this project
- **Yuyz0112** for the [claude-code-reverse](https://github.com/Yuyz0112/claude-code-reverse) project, and **shareAI-lab** for the [Kode](https://github.com/shareAI-lab/Kode) project, both of which provided inspiration for the Claude code agent development in this project

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Pywen - Making the power of Qwen3-Coder accessible for intelligent software development!** 🚀

**PAMPAS-Lab - Dedicated to breakthroughs in large model agent frameworks, bridging AI research and applications!** 🚀

---

## 🌟Star History

[![Star History Chart](https://api.star-history.com/svg?repos=PAMPAS-Lab/Pywen&type=Date)](https://www.star-history.com/#PAMPAS-Lab/Pywen&Date)
