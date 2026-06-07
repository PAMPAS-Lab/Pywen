from pywen.tools.tool_manager import ToolManager


def test_tools_autodiscover():
    ToolManager.autodiscover()

    tools = ToolManager.list_for_provider("codex")
    print("codex tools:")
    for tool in tools:
        print(tool.name)

    print("\nqwen tools:")
    tools = ToolManager.list_for_provider("qwen")
    for tool in tools:
        print(tool.name)

    print("\nclaude tools:")
    tools = ToolManager.list_for_provider("claude")
    for tool in tools:
        print(tool.name)

    assert len(tools) > 0, "No tools found for provider 'claude'"
