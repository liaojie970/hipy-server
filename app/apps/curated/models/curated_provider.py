#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : curated_provider.py
# 精选内容 - 站点/账号配置
from db.base_class import Base
from db import fields


class CuratedProvider(Base):
    """精选内容站点/账号配置 (如 B站登录账号)"""
    __tablename__ = 'curated_provider'

    name = fields.Char(string='站点名称', required=True)
    code = fields.Char(string='站点编码', required=True)
    config = fields.Text(string='站点配置(JSON, 如cookie)')
    status = fields.Integer(string='状态:0停用,1启用', default=1)
    order_num = fields.Integer(string='显示排序', default=1)
    remark = fields.Char(string='备注')
