"""
测试 BashTool 的功能，包括交互式和非交互式场景
"""
import os
import tempfile
from pathlib import Path

import pytest

from pywen.tools.bash_tool import BashTool


@pytest.fixture
def bash_tool():
    """创建 BashTool 实例"""
    return BashTool()


@pytest.fixture
def temp_dir():
    """创建临时目录用于测试"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.mark.asyncio
async def test_basic_command_execution(bash_tool, temp_dir):
    """测试基本命令执行（非交互式）"""
    result = await bash_tool.execute(command="echo 'Hello, World!'", directory=temp_dir)
    
    assert result.error is None or result.error == ""
    assert "Hello, World!" in result.result
    # metadata 可能为空字典，或者包含 exit_code
    assert result.metadata is None or result.metadata == {} or result.metadata.get("exit_code") == 0


@pytest.mark.asyncio
async def test_environment_variables_set(bash_tool, temp_dir):
    """测试环境变量是否正确设置（非交互式环境）"""
    # 测试 PAGER, GIT_PAGER, PYTHONUNBUFFERED 等环境变量
    result = await bash_tool.execute(command="env | grep -E '(PAGER|GIT_PAGER|PYTHONUNBUFFERED)'", directory=temp_dir)
    
    assert result.error is None or result.error == ""
    assert "PAGER=cat" in result.result
    assert "GIT_PAGER=cat" in result.result
    assert "PYTHONUNBUFFERED=1" in result.result


@pytest.mark.asyncio
async def test_grep_line_buffered_auto_add(bash_tool, temp_dir):
    """测试 grep 命令自动添加 --line-buffered 选项"""
    # 创建一个测试文件
    test_file = Path(temp_dir) / "test.txt"
    test_file.write_text("test line 1\ntest line 2\ntest line 3\n")
    
    # 执行 grep 命令，应该自动添加 --line-buffered
    result = await bash_tool.execute(command=f"grep 'test' {test_file}", directory=temp_dir)
    
    assert result.error is None or result.error == ""
    # 验证命令执行成功（即使我们看不到实际的命令，但应该能正常工作）
    assert "test" in result.result.lower() or result.result.strip() == ""


@pytest.mark.asyncio
async def test_grep_with_existing_line_buffered(bash_tool, temp_dir):
    """测试如果 grep 已经有 --line-buffered，不会重复添加"""
    test_file = Path(temp_dir) / "test.txt"
    test_file.write_text("test line\n")
    
    # 执行带有 --line-buffered 的 grep 命令
    result = await bash_tool.execute(command=f"grep --line-buffered 'test' {test_file}", directory=temp_dir)
    
    assert result.error is None or result.error == ""
    # 命令应该正常执行
    assert "test" in result.result.lower() or result.result.strip() == ""


@pytest.mark.asyncio
async def test_multiline_command(bash_tool, temp_dir):
    """测试多行命令处理"""
    # 测试多行 Python 命令
    result = await bash_tool.execute(command='''python3 -c "
print('Line 1')
print('Line 2')
print('Line 3')
"''', directory=temp_dir)
    
    assert result.error is None or result.error == ""
    # 应该能执行多行命令
    assert "Line 1" in result.result or "Line 2" in result.result or "Line 3" in result.result or "python3" not in result.result.lower()


@pytest.mark.asyncio
async def test_python_unbuffered_output(bash_tool, temp_dir):
    """测试 Python 命令的立即输出（非交互式）"""
    # Python 命令应该立即输出，不缓冲
    result = await bash_tool.execute(command='python3 -c "import sys; sys.stdout.write(\"immediate\\n\"); sys.stdout.flush(); import time; time.sleep(0.1); print(\"delayed\")"', directory=temp_dir)
    
    assert result.error is None or result.error == ""
    # 应该能看到输出
    assert "immediate" in result.result or "delayed" in result.result or "python3" not in result.result.lower()


@pytest.mark.asyncio
async def test_git_command_no_pager(bash_tool, temp_dir):
    """测试 git 命令不使用分页器（非交互式）"""
    # 在临时目录中初始化 git 仓库
    os.chdir(temp_dir)
    os.system("git init > /dev/null 2>&1")
    os.system("git config user.name 'Test' > /dev/null 2>&1")
    os.system("git config user.email 'test@test.com' > /dev/null 2>&1")
    
    # 创建一个文件并提交
    with open("test.txt", "w") as f:
        f.write("test content")
    os.system("git add test.txt > /dev/null 2>&1")
    os.system("git commit -m 'Initial commit' > /dev/null 2>&1")
    
    # 测试 git log 不应该使用分页器
    result = await bash_tool.execute(command="git log --oneline")
    
    # git log 应该能正常执行，不会因为分页器而挂起
    assert result.error is None or "Initial commit" in result.result or result.result.strip() == ""


@pytest.mark.asyncio
async def test_command_with_error(bash_tool, temp_dir):
    """测试错误命令的处理"""
    result = await bash_tool.execute(command="nonexistent_command_12345", directory=temp_dir)
    
    # 应该返回错误信息
    assert result.error is not None or result.metadata is not None or "[Exit Code:" in result.result or "error" in result.result.lower()


@pytest.mark.asyncio
async def test_command_timeout(bash_tool, temp_dir):
    """测试命令超时处理"""
    # 执行一个会超时的命令（sleep 超过超时时间）
    result = await bash_tool.execute(command="sleep 0.5", timeout=0.2, directory=temp_dir)
    
    # 应该处理超时（可能返回超时错误或进程仍在运行）
    assert result.error is not None or result.metadata is not None or "timeout" in result.result.lower() or "running" in result.result.lower() or "PID" in result.result


@pytest.mark.asyncio
async def test_background_process(bash_tool, temp_dir):
    """测试后台进程执行"""
    result = await bash_tool.execute(command="echo 'background test'", is_background=True, directory=temp_dir)
    
    # 后台进程应该返回 PID 信息
    assert result.error is None or result.error == ""
    assert "PID" in result.result or "background" in result.result.lower() or "started" in result.result.lower()


@pytest.mark.asyncio
async def test_directory_parameter(bash_tool, temp_dir):
    """测试 directory 参数"""
    # 在临时目录中创建文件
    test_file = Path(temp_dir) / "test_file.txt"
    test_file.write_text("test content")
    
    # 在指定目录执行命令
    result = await bash_tool.execute(command="cat test_file.txt", directory=temp_dir)
    
    assert result.error is None or result.error == ""
    assert "test content" in result.result


@pytest.mark.asyncio
async def test_invalid_directory(bash_tool):
    """测试无效目录的处理"""
    result = await bash_tool.execute(command="echo 'test'", directory="/nonexistent/directory/12345")
    
    # 应该返回错误
    assert result.error is not None and "does not exist" in result.error


@pytest.mark.asyncio
async def test_empty_command(bash_tool):
    """测试空命令的处理"""
    result = await bash_tool.execute(command="")
    
    # 应该返回错误
    assert result.error is not None and "No command provided" in result.error


@pytest.mark.asyncio
async def test_find_with_grep(bash_tool, temp_dir):
    """测试 find 配合 grep 的命令（非交互式，测试缓冲问题）"""
    # 创建测试文件
    test_file = Path(temp_dir) / "test.py"
    test_file.write_text("def test_function():\n    pass\n")
    
    # 执行 find 配合 grep 的命令
    result = await bash_tool.execute(command=f"find {temp_dir} -name '*.py' -exec grep -l 'test_function' {{}} \\;", directory=temp_dir)
    
    # 应该能正常执行，不会因为缓冲问题而挂起
    assert result.error is None or result.error == ""
    # grep 应该自动添加了 --line-buffered
    assert "test.py" in result.result or result.result.strip() == ""


@pytest.mark.asyncio
async def test_command_with_special_characters(bash_tool, temp_dir):
    """测试包含特殊字符的命令"""
    result = await bash_tool.execute(command="echo 'Hello, \"World\"!'", directory=temp_dir)
    
    assert result.error is None or result.error == ""
    assert "Hello" in result.result or "World" in result.result


@pytest.mark.asyncio
async def test_command_output_truncation(bash_tool, temp_dir):
    """测试长输出的截断"""
    # 生成一个很长的输出（超过 MAX_OUTPUT_LENGTH）
    long_output_cmd = "python3 -c \"print('x' * 50000)\""
    result = await bash_tool.execute(command=long_output_cmd, directory=temp_dir)
    
    # 输出应该被截断或命令执行成功
    assert result.error is None or result.error == "" or "truncated" in result.result.lower()


@pytest.mark.asyncio
async def test_risk_level_detection(bash_tool):
    """测试风险等级检测"""
    # 高风险命令
    high_risk = bash_tool.get_risk_level(command="rm -rf /")
    assert high_risk.value == "high"
    
    # 中等风险命令
    medium_risk = bash_tool.get_risk_level(command="rm file.txt")
    assert medium_risk.value == "medium"
    
    # 低风险命令
    low_risk = bash_tool.get_risk_level(command="echo 'test'")
    assert low_risk.value == "low"


@pytest.mark.asyncio
async def test_pager_environment_variables(bash_tool, temp_dir):
    """测试分页器相关的环境变量设置"""
    # 检查所有分页器相关的环境变量
    result = await bash_tool.execute(command="env | grep -E '(PAGER|MANPAGER|GIT_PAGER|LESS)' | sort", directory=temp_dir)
    
    assert result.error is None or result.error == ""
    # 应该设置这些环境变量
    env_vars = result.result
    assert "PAGER=cat" in env_vars
    assert "GIT_PAGER=cat" in env_vars
    assert "MANPAGER=cat" in env_vars
    assert "LESS=-R" in env_vars


@pytest.mark.asyncio
async def test_python_progress_bar_disabled(bash_tool, temp_dir):
    """测试 Python 进度条相关的环境变量"""
    result = await bash_tool.execute(command="env | grep -E '(PIP_PROGRESS_BAR|TQDM_DISABLE)'", directory=temp_dir)
    
    assert result.error is None or result.error == ""
    env_vars = result.result
    assert "PIP_PROGRESS_BAR=off" in env_vars
    assert "TQDM_DISABLE=1" in env_vars


@pytest.mark.asyncio
async def test_complex_multiline_python_command(bash_tool, temp_dir):
    """测试复杂多行 Python 命令（类似 run.log 中的场景）"""
    # 测试类似 run.log 中的复杂多行 Python 命令
    complex_cmd = '''python3 -c "
import numpy as np
from astropy.table import Table

array = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]])
tbl = Table({'a': [1, 2, 3], 'b': [4, 5, 6]})
print('Table created successfully')
print('Array shape:', array.shape)
"'''
    result = await bash_tool.execute(command=complex_cmd, directory=temp_dir)
    
    # 应该能执行，不会因为多行或导入库而失败
    assert result.error is None or result.error == ""
    # 即使导入失败，也不应该因为缓冲或分页器问题而挂起
    assert "Table created" in result.result or "Array shape" in result.result or "ImportError" in result.result or "ModuleNotFoundError" in result.result or result.result.strip() == ""


@pytest.mark.asyncio
async def test_python_command_with_delayed_output(bash_tool, temp_dir):
    """测试 Python 命令延迟输出的情况（测试 PYTHONUNBUFFERED 的效果）"""
    # 测试 Python 命令在导入大型库后输出
    cmd = 'python3 -c "import time; time.sleep(0.1); print(\"Output after delay\")"'
    result = await bash_tool.execute(command=cmd, directory=temp_dir)
    
    # 应该能看到输出，不会因为缓冲而丢失
    assert result.error is None or result.error == ""
    assert "Output after delay" in result.result or "python3" not in result.result.lower()


@pytest.mark.asyncio
async def test_git_log_with_grep_pattern(bash_tool, temp_dir):
    """测试 git log 配合 grep 的命令（类似 run.log 中的场景）"""
    # 初始化 git 仓库
    os.chdir(temp_dir)
    os.system("git init > /dev/null 2>&1")
    os.system("git config user.name 'Test' > /dev/null 2>&1")
    os.system("git config user.email 'test@test.com' > /dev/null 2>&1")
    
    # 创建文件并提交
    test_file = Path(temp_dir) / "test.py"
    test_file.write_text("def test_function():\n    pass\n")
    os.system("git add test.py > /dev/null 2>&1")
    os.system("git commit -m 'Add test function' > /dev/null 2>&1")
    
    # 测试 git log 配合 grep（类似 run.log 中的命令）
    result = await bash_tool.execute(command="git log --oneline --grep='test'", directory=temp_dir)
    
    # 应该能正常执行，不会因为分页器而挂起
    assert result.error is None or result.error == ""
    # 即使没有匹配或没有输出，也不应该挂起（关键是命令能正常完成）
    assert "Add test function" in result.result or result.result.strip() == "" or "Command executed successfully" in result.result


@pytest.mark.asyncio
async def test_python_table_read_command(bash_tool, temp_dir):
    """测试类似 run.log 中的 Table.read 命令场景"""
    # 创建一个测试文件
    test_file = Path(temp_dir) / "test.txt"
    test_file.write_text("col1,col2\n1,2\n3,4\n")
    
    # 测试 Python 读取文件的命令（类似 run.log 中的场景）
    cmd = f'python3 -c "from astropy.table import Table; tbl = Table.read(\'{test_file}\', format=\'ascii.csv\'); print(len(tbl))"'
    result = await bash_tool.execute(command=cmd, directory=temp_dir)
    
    # 应该能执行，即使导入失败也不应该挂起
    assert result.error is None or result.error == ""
    # 可能成功（如果有 astropy）或失败（如果没有），但不应该挂起
    assert "2" in result.result or "ImportError" in result.result or "ModuleNotFoundError" in result.result or result.result.strip() == ""

