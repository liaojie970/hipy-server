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
    remark = fields.Char(string='备注')
