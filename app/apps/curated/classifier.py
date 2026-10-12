#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : classifier.py
# 精选内容 - 按标题关键词自动归类
"""
把「搜索入库时忘记选分类」的未分类内容按标题关键词归到已有分类。

规则顺序即优先级(先命中先归类); 英语作为默认兜底分类, 因为库内绝大多数是
英语启蒙内容, 且用户确认「小猪佩奇/海绵宝宝/奇幻沼泽」等英文动画也归入英语。

供两处共用:
1. 后台「内容库」的「智能归类」按钮 (service.CuratedService.auto_classify);
2. 一次性数据修复脚本。
"""
import re
from typing import List

# 顺序即优先级; 第一个命中的规则生效
RULES = [
    ('语文', r'(?<!双)语文|大语文|国学|唐诗|宋词|古诗|汉字|拼音|成语|三字经|弟子规|千字文|三十六计|文言文|跟着书本去旅行'),
    ('数学', r'数学|数字积木|奥数|几何|算术|数理'),
    ('艺术', r'写字|书法|美术|绘画|声乐|钢琴|乐器|舞蹈|武术'),
    ('儿童科普纪录片',
     r'纪录片|科普|百科|国家地理|National Geographic|微观小世界|小小世界|神奇校车|昆虫|恐龙|STEM|大自然|自然界'),
    # 英语优先于「奥斯卡/经典动画」: 避免把英语启蒙的「西游记英文版经典动画」等误归动画
    ('英语',
     r'英语|英文|英文字幕|双语|双字幕|美语|美音|口语|听力|音标|自然拼读|单词|词汇|磨耳朵|'
     r'新概念|走遍美国|雅思|托福|English|Phonics|字母积木|分级阅读|绘本|播客|Podcast'),
    ('奥斯卡奖&经典动画', r'奥斯卡|动画短片|经典动画'),
]

# 未命中任何规则时的兜底分类
DEFAULT_CATEGORY = '英语'

_COMPILED = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in RULES]


def classify_title(title: str) -> str:
    """按标题关键词返回分类名称(未命中返回默认分类)。"""
    text = title or ''
    for name, pattern in _COMPILED:
        if pattern.search(text):
            return name
    return DEFAULT_CATEGORY


def classify_titles(titles: List[str]) -> List[str]:
    """批量归类, 返回与入参等长的分类名列表。"""
    return [classify_title(t) for t in titles]
