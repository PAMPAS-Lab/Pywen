from pywen.core.tool_registry2 import tools_autodiscover, list_tools_for_provider

def test_tools_autodiscover():
    tools_autodiscover()
    tools = list_tools_for_provider("codex")
    print("codex tools:")
    for tool in tools:
        print(tool.name)

    print("\nqwen tools:")
    tools = list_tools_for_provider("qwen")
    for tool in tools:
        print(tool.name)

    print("\nclaude tools:")
    tools = list_tools_for_provider("claude")
    for tool in tools:
        print(tool.name)

    assert len(tools) > 0, "No tools found for provider 'openai'"
