"""计算器工具测试：算得对，也挡得住危险表达式。"""

import asyncio

import pytest

from app.tools.base import ToolError
from app.tools.calculator import CalculatorTool, safe_calculate


def test_basic_arithmetic() -> None:
    assert safe_calculate("2+3*4") == 14
    assert safe_calculate("(2+3)*4") == 20
    assert safe_calculate("2**10") == 1024
    assert safe_calculate("sqrt(16)") == 4


def test_formats_integer_result() -> None:
    tool = CalculatorTool()
    result = asyncio.run(tool.run(1, {"expression": "25*4"}))
    assert result == "25*4 = 100"


def test_rejects_dangerous_expression() -> None:
    with pytest.raises(ToolError):
        safe_calculate('__import__("os").system("whoami")')


def test_rejects_bad_math() -> None:
    with pytest.raises(ToolError):
        safe_calculate("1/0")
    with pytest.raises(ToolError):
        safe_calculate("2**1000")
    with pytest.raises(ToolError):
        safe_calculate("(1+2")
