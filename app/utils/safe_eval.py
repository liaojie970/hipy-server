# -*- coding: utf-8 -*-
"""
File  : safe_eval.py
安全的表达式求值工具。

背景: 项目原先直接使用 ``numpy.safe_eval``，而 ``numpy.safe_eval`` 的内部实现
就是 ``ast.literal_eval``。手机(Termux/Android)等环境不安装 numpy 时，
导入会直接失败，因此统一收敛到这里，避免不必要的 numpy 依赖。
"""
import ast


def safe_eval(source):
    """
    安全地求值一个仅包含 Python 字面量表达式的字符串, 禁止执行任意代码。
    行为等价于 numpy.safe_eval / ast.literal_eval。

    :param source: 待求值表达式, 如 "[1, 2, 3]" / "{'a': 1}" / "hello"
    :return: 求值结果
    """
    return ast.literal_eval(source)
