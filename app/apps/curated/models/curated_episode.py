#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : curated_episode.py
# 精选内容 - 媒体选集(多P/分集)
from db.base_class import Base
from db import fields


class CuratedEpisode(Base):
    """精选媒体选集"""
    __tablename__ = 'curated_episode'

    media_id = fields.Integer(string='关联媒体id', required=True)
    page_index = fields.Integer(string='分P序号', default=0)
    cid = fields.Char(string='分集cid')
    title = fields.Char(string='分集标题', length=512)
    duration = fields.Integer(string='时长(秒)')
    order_num = fields.Integer(string='显示排序', default=1)
