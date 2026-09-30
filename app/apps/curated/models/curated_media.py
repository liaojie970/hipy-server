#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : curated_media.py
# 精选内容 - 已入库媒体(需人工审核)
from sqlalchemy import UniqueConstraint

from db.base_class import Base
from db import fields

# 数据库层面的硬约束: 同一站点内同一个媒体只能有一行(应用层去重的兜底保障)
UNIQUE_NAME = 'uq_curated_media_provider_media'


class CuratedMedia(Base):
    """精选媒体 (通过人工审核后才对客户端可见)"""
    __tablename__ = 'curated_media'
    __table_args__ = (
        UniqueConstraint('provider_code', 'media_id', name=UNIQUE_NAME),
    )

    provider_code = fields.Char(string='站点编码', required=True)
    media_id = fields.Char(string='站点内媒体ID(如bvid)', required=True)
    title = fields.Char(string='标题', length=512)
    cover = fields.Text(string='封面')
    description = fields.Text(string='简介')
    duration = fields.Integer(string='时长(秒)')
    up_name = fields.Char(string='作者/UP主')
    up_mid = fields.Char(string='作者ID')
    category_id = fields.Integer(string='所属分类id')
    tags = fields.Char(string='标签(逗号分隔)')
    source_url = fields.Text(string='原始链接')
    extra = fields.Text(string='扩展信息(JSON)')
    play_count = fields.Integer(string='播放量')
    # 审核状态: 0待审核, 1已通过, 2已拒绝
    status = fields.Integer(string='审核状态:0待审,1通过,2拒绝', default=0)
    # 前台是否可见
    visible = fields.Integer(string='前台可见:0否,1是', default=1)
    # 可见性/可播放校验: 0未校验, 1正常, 2异常
    view_status = fields.Integer(string='校验:0未校验,1正常,2异常', default=0)
    check_time = fields.Datetime(string='最近校验时间')
    order_num = fields.Integer(string='显示排序', default=1)
    remark = fields.Char(string='备注')
