#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : classifier.py
# 精选内容 - 按标题关键词自动归类(动态读取「分类管理」)
"""
规则不再硬编码, 完全来自「分类管理」(curated_category) 的三个字段:

- `keywords`   匹配关键词, 每行一个(支持正则), 命中任意一行即归入该分类;
- `order_num`  匹配优先级, 数值小者先匹配(即列表里的「排序」, 可自行调整);
- `is_default` =1 表示「兜底分类」, 标题未命中任何关键词时归入该分类。

只处理未分类记录, 不覆盖已有分类。供后台「内容库」的「智能归类」按钮使用。
"""
import re
from typing import List, Optional

# 「分类管理」未设置任何兜底分类(is_default)时的最后回退名称
DEFAULT_FALLBACK_NAME = '英语'

# 规则: (分类名, [已编译正则, ...])
Rule = tuple


def _compile_keywords(text: str) -> list:
    """把多行关键词编译为正则列表; 非法正则的行忽略。"""
    patterns = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            patterns.append(re.compile(line, re.IGNORECASE))
        except re.error:
            continue
    return patterns


def _sort_key(c: dict):
    return (c.get('order_num') or 0, c.get('id') or 0)


def compile_rules(categories: List[dict]) -> List[Rule]:
    """把分类列表编译成规则, 按 order_num 升序(先命中先归类)。"""
    rules = []
    for c in sorted(categories, key=_sort_key):
        name = c.get('name')
        patterns = _compile_keywords(c.get('keywords'))
        if name and patterns:
            rules.append((name, patterns))
    return rules


def pick_default_name(categories: List[dict]) -> Optional[str]:
    """取兜底分类名称: 优先 is_default=1; 否则回退 DEFAULT_FALLBACK_NAME(若存在)。"""
    for c in sorted(categories, key=_sort_key):
        if (c.get('is_default') or 0) == 1 and c.get('name'):
            return c['name']
    names = {c.get('name') for c in categories}
    return DEFAULT_FALLBACK_NAME if DEFAULT_FALLBACK_NAME in names else None


def classify_title(title: str, rules: List[Rule]) -> Optional[str]:
    """按规则返回命中的分类名称; 未命中返回 None(由调用方决定兜底)。"""
    text = title or ''
    for name, patterns in rules:
        for p in patterns:
            if p.search(text):
                return name
    return None


def classify_titles(titles: List[str], rules: List[Rule]) -> List[Optional[str]]:
    """批量归类, 返回与入参等长的分类名(或 None)列表。"""
    return [classify_title(t, rules) for t in titles]
