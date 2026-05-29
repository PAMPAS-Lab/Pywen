import pytest

from pywen.tools.grep_tool import GrepTool


@pytest.mark.asyncio
async def test_grep_reports_invalid_regex(tmp_path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("hello\n", encoding="utf-8")

    result = await GrepTool().execute(
        pattern="[",
        path=str(test_file),
        regex=True,
    )

    assert result.error is not None
    assert "Invalid regex pattern" in result.error


@pytest.mark.asyncio
async def test_grep_regex_matches_file_content(tmp_path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("alpha\nbeta-123\n", encoding="utf-8")

    result = await GrepTool().execute(
        pattern=r"beta-\d+",
        path=str(test_file),
        regex=True,
    )

    assert result.error is None
    assert f"{test_file}:2:beta-123" in result.result


@pytest.mark.asyncio
async def test_grep_plain_text_case_insensitive(tmp_path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("Pywen Agent\n", encoding="utf-8")

    result = await GrepTool().execute(
        pattern="pywen",
        path=str(test_file),
        case_sensitive=False,
    )

    assert result.error is None
    assert f"{test_file}:1:Pywen Agent" in result.result
