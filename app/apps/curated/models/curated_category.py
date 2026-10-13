#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : curated_category.py
# 精选内容 - 内容分类
from db.base_class import Base
from db import fields


class CuratedCategory(Base):
    """精选内容分类 (如: 语文/数学/科普)"""
    __tablename__ = 'curated_category'

    name = fields.Char(string='分类名称', required=True)
    icon = fields.Char(string='分类图标')
    status = fields.Integer(string='状态:0停用,1启用', default=1)
    order_num = fields.Integer(string='显示排序', default=1)
    # 智能归类: 匹配关键词(每行一个正则, 命中即归入本分类)
    keywords = fields.Text(string='智能归类关键词(每行一个, 支持正则)')
    # 智能归类: 兜底分类(标题未命中任何关键词时归入, 建议全局只设一个)
    is_default = fields.Integer(string='是否兜底分类:0否,1是', default=0)
    remark = fields.Char(string='备注')
