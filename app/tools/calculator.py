"""计算器工具：只算数，不执行任意代码。

不用 eval：把表达式交给 ast 解析，只允许数字、四则运算、乘方和少量数学函数。
"""

import ast
import math
import operator
from typing import Any

from app.tools.base import BaseTool, ToolError

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_FUNCTIONS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
}

_CONSTANTS = {"pi": math.pi, "e": math.e}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ToolError("表达式里只能出现数字")
        return node.value

    if isinstance(node, ast.BinOp):
        func = _BIN_OPS.get(type(node.op))
        if func is None:
            raise ToolError("不支持的运算符")
        left = _eval(node.left)
        right = _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ToolError("指数太大，换个写法")
        try:
            return func(left, right)
        except ZeroDivisionError as exc:
            raise ToolError("除数不能为 0") from exc
        except OverflowError as exc:
            raise ToolError("结果太大，算不出来") from exc

    if isinstance(node, ast.UnaryOp):
        func = _UNARY_OPS.get(type(node.op))
        if func is None:
            raise ToolError("不支持的一元运算符")
        return func(_eval(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ToolError("不支持的函数")
        if node.keywords:
            raise ToolError("函数不支持关键字参数")
        args = [_eval(arg) for arg in node.args]
        if len(args) != 1:
            raise ToolError("函数只支持 1 个参数")
        try:
            return _FUNCTIONS[node.func.id](args[0])
        except (ValueError, OverflowError) as exc:
            raise ToolError("函数计算失败，检查一下参数范围") from exc

    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]

    raise ToolError("表达式里只能有数字、运算符和允许的函数")


def safe_calculate(expression: str) -> float:
    expression = expression.strip()
    if not expression:
        raise ToolError("表达式不能为空")
    if len(expression) > 200:
        raise ToolError("表达式太长了，控制在 200 个字符以内")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError("表达式语法不对") from exc

    value = _eval(tree.body)
    if isinstance(value, float) and not math.isfinite(value):
        raise ToolError("结果不是有限数字")
    return value


def format_number(value: float) -> str:
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


class CalculatorTool(BaseTool):
    name = "calculator"
    description = (
        "做算术计算。支持 + - * / // % **、括号，以及 sqrt/sin/cos/tan/log/log10/exp/abs "
        "和常数 pi/e。当用户让你算数、验算、换算时使用；不要心算。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "要计算的数学表达式，例如 (25*4+10)/2 或 sqrt(16)",
            }
        },
        "required": ["expression"],
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        expression = str(arguments.get("expression", ""))
        value = safe_calculate(expression)
        return f"{expression} = {format_number(value)}"
