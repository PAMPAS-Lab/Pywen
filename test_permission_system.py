#!/usr/bin/env python3
"""
Test script to verify the new permission system works correctly
"""

import sys
import os
import asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pywen.core.permission_manager import PermissionManager, PermissionLevel
from pywen.config.config import Config, ModelConfig, ModelProvider

async def test_permission_manager():
    """Test the PermissionManager functionality"""
    print("🧪 Testing PermissionManager...")
    
    # Test all permission levels
    levels = [
        PermissionLevel.LOCKED,
        PermissionLevel.EDIT_ONLY, 
        PermissionLevel.PLANNING,
        PermissionLevel.YOLO
    ]
    
    test_tools = [
        ("write_file", {"path": "test.py", "content": "print('hello')"}),
        ("read_file", {"path": "test.py"}),
        ("bash", {"command": "ls -la"}),
        ("bash", {"command": "rm -rf /"}),  # Dangerous command
        ("web_search", {"query": "python tutorial"}),
        ("agent_tool", {"task": "analyze code"})
    ]
    
    for level in levels:
        print(f"\n📋 Testing {level.value.upper()} level:")
        manager = PermissionManager(level)
        print(f"   Description: {manager.get_permission_description()}")
        
        for tool_name, kwargs in test_tools:
            should_approve = manager.should_auto_approve(tool_name, **kwargs)
            status = "✅ Auto-approve" if should_approve else "❓ Needs confirmation"
            category = manager.get_tool_category(tool_name) or "unknown"
            print(f"   {tool_name}: {status} ({category})")
    
    return True

async def test_config_integration():
    """Test Config integration with PermissionManager"""
    print("\n🔧 Testing Config integration...")
    
    # Create a test config
    config = Config(
        model_config=ModelConfig(
            provider=ModelProvider.ANTHROPIC,
            model="claude-3-sonnet-20240229",
            api_key="test-key"
        ),
        permission_level=PermissionLevel.EDIT_ONLY
    )
    
    # Test permission manager access
    permission_manager = config.get_permission_manager()
    current_level = permission_manager.get_permission_level()
    print(f"✅ Config permission level: {current_level.value}")
    
    # Test level changes
    config.set_permission_level(PermissionLevel.YOLO)
    new_level = permission_manager.get_permission_level()
    print(f"✅ Updated permission level: {new_level.value}")
    
    # Test tool permission check
    should_approve = permission_manager.should_auto_approve("write_file", path="test.py", content="hello")
    print(f"✅ write_file auto-approve: {should_approve}")
    
    return True

async def test_permission_command():
    """Test permission command functionality"""
    print("\n📋 Testing permission command...")
    
    try:
        from pywen.ui.commands.permission_command import PermissionCommand
        
        command = PermissionCommand()
        print(f"✅ Permission command created: {command.name}")
        print(f"   Aliases: {command.aliases}")
        print(f"   Description: {command.description}")
        
        return True
    except Exception as e:
        print(f"❌ Permission command test failed: {e}")
        return False

async def test_tool_categories():
    """Test tool categorization"""
    print("\n🔍 Testing tool categories...")
    
    manager = PermissionManager()
    
    test_cases = [
        ("write_file", "file_edit"),
        ("read_file", "file_read"),
        ("ls", "file_system"),
        ("bash", "system_command"),
        ("web_search", "network"),
        ("memory", "memory"),
        ("agent_tool", "agent"),
        ("unknown_tool", None)
    ]
    
    for tool_name, expected_category in test_cases:
        actual_category = manager.get_tool_category(tool_name)
        if actual_category == expected_category:
            print(f"✅ {tool_name}: {actual_category or 'None'}")
        else:
            print(f"❌ {tool_name}: expected {expected_category}, got {actual_category}")
            return False
    
    return True

async def main():
    """Run all tests"""
    print("🚀 Starting permission system tests...\n")
    
    try:
        success1 = await test_permission_manager()
        success2 = await test_config_integration()
        success3 = await test_permission_command()
        success4 = await test_tool_categories()
        
        print(f"\n📊 Test Results:")
        print(f"   Permission Manager: {'✅ PASS' if success1 else '❌ FAIL'}")
        print(f"   Config Integration: {'✅ PASS' if success2 else '❌ FAIL'}")
        print(f"   Permission Command: {'✅ PASS' if success3 else '❌ FAIL'}")
        print(f"   Tool Categories: {'✅ PASS' if success4 else '❌ FAIL'}")
        
        if success1 and success2 and success3 and success4:
            print("\n🎉 All tests passed!")
            print("\n📝 Available permission levels:")
            manager = PermissionManager()
            for level, desc in manager.get_available_levels().items():
                print(f"   {level}: {desc}")
            print("\n💡 Use '/permission <level>' to change permission level in CLI")
            return True
        else:
            print("\n💥 Some tests failed!")
            return False
            
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
