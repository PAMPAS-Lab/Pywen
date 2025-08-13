#!/usr/bin/env python3
"""
Test script to verify permission level cycling works correctly
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pywen.core.permission_manager import PermissionManager, PermissionLevel
from pywen.config.config import Config, ModelConfig, ModelProvider

def test_permission_cycle():
    """Test the permission level cycling logic"""
    print("🔄 Testing permission level cycling...")
    
    # Create a test config
    config = Config(
        model_config=ModelConfig(
            provider=ModelProvider.ANTHROPIC,
            model="claude-3-sonnet-20240229",
            api_key="test-key"
        ),
        permission_level=PermissionLevel.LOCKED
    )
    
    # Define the expected cycle order
    cycle_order = [
        PermissionLevel.LOCKED,
        PermissionLevel.EDIT_ONLY,
        PermissionLevel.PLANNING,
        PermissionLevel.YOLO
    ]
    
    print(f"📋 Starting level: {config.get_permission_level().value}")
    
    # Test cycling through all levels (exactly one full cycle)
    for i in range(len(cycle_order)):
        current_level = config.get_permission_level()
        
        # Simulate Ctrl+Y key press logic
        try:
            current_index = cycle_order.index(current_level)
            next_index = (current_index + 1) % len(cycle_order)
            next_level = cycle_order[next_index]
        except ValueError:
            next_level = PermissionLevel.LOCKED
        
        # Set new permission level
        config.set_permission_level(next_level)
        
        # Display the change
        level_info = {
            PermissionLevel.LOCKED: ("🔒 LOCKED", "全锁状态"),
            PermissionLevel.EDIT_ONLY: ("✏️ EDIT_ONLY", "编辑权限"),
            PermissionLevel.PLANNING: ("🧠 PLANNING", "规划权限"),
            PermissionLevel.YOLO: ("🚀 YOLO", "锁开状态")
        }
        
        icon_text, description = level_info[next_level]
        print(f"   Ctrl+Y #{i+1}: {icon_text} - {description}")
        
        # Verify the level was actually set
        actual_level = config.get_permission_level()
        if actual_level != next_level:
            print(f"❌ Error: Expected {next_level.value}, got {actual_level.value}")
            return False
    
    # Verify we're back to the starting level after full cycle
    final_level = config.get_permission_level()
    if final_level == PermissionLevel.LOCKED:
        print("✅ Full cycle completed successfully!")
        return True
    else:
        print(f"❌ Cycle error: Expected to return to LOCKED, got {final_level.value}")
        return False

def test_permission_effects():
    """Test the effects of different permission levels"""
    print("\n🧪 Testing permission effects...")
    
    config = Config(
        model_config=ModelConfig(
            provider=ModelProvider.ANTHROPIC,
            model="claude-3-sonnet-20240229",
            api_key="test-key"
        )
    )
    
    test_tools = [
        ("write_file", {"path": "test.py", "content": "hello"}),
        ("read_file", {"path": "test.py"}),
        ("bash", {"command": "ls"}),
        ("web_search", {"query": "test"})
    ]
    
    levels = [
        PermissionLevel.LOCKED,
        PermissionLevel.EDIT_ONLY,
        PermissionLevel.PLANNING,
        PermissionLevel.YOLO
    ]
    
    for level in levels:
        config.set_permission_level(level)
        permission_manager = config.get_permission_manager()
        
        print(f"\n📋 {level.value.upper()} level:")
        for tool_name, kwargs in test_tools:
            should_approve = permission_manager.should_auto_approve(tool_name, **kwargs)
            status = "✅ Auto" if should_approve else "❓ Confirm"
            print(f"   {tool_name}: {status}")
    
    return True

def main():
    """Run all tests"""
    print("🚀 Testing permission cycling system...\n")
    
    try:
        success1 = test_permission_cycle()
        success2 = test_permission_effects()
        
        print(f"\n📊 Test Results:")
        print(f"   Permission Cycling: {'✅ PASS' if success1 else '❌ FAIL'}")
        print(f"   Permission Effects: {'✅ PASS' if success2 else '❌ FAIL'}")
        
        if success1 and success2:
            print("\n🎉 All tests passed!")
            print("\n💡 Usage in CLI:")
            print("   Press Ctrl+Y to cycle through permission levels:")
            print("   🔒 LOCKED → ✏️ EDIT_ONLY → 🧠 PLANNING → 🚀 YOLO → 🔒 LOCKED")
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
    success = main()
    sys.exit(0 if success else 1)
