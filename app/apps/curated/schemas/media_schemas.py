#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : media_schemas.py
from typing import Optional

from pydantic import BaseModel


class CuratedMediaSchema(BaseModel):
    provider_code: Optional[str] = None
    media_id: Optional[str] = None
    title: Optional[str] = None
    cover: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[int] = 0
    up_name: Optional[str] = None
    up_mid: Optional[str] = None
    category_id: Optional[int] = None
    tags: Optional[str] = None
    source_url: Optional[str] = None
    extra: Optional[str] = None
    status: Optional[int] = None
    visible: Optional[int] = None
    order_num: Optional[int] = None
    remark: Optional[str] = None


class CuratedMediaQuerySchema(BaseModel):
    provider_code: Optional[str] = None
    category_id: Optional[int] = None
    status: Optional[int] = None
    visible: Optional[int] = None
    keyword: Optional[str] = None
    page: int = 1
    page_size: int = 25


class CuratedMediaBatchSchema(BaseModel):
    """批量入库(勾选搜索结果/粘贴链接解析后)"""
    provider_code: str
    category_id: Optional[int] = None
    status: int = 1
    visible: int = 1
    # 已存在的(provider_code + media_id)是否跳过, 默认跳过以保证重复点击幂等
    skip_existing: bool = True
    # 已存在时是否重新联网刷新详情(选集/封面等)
    refresh: bool = False
    # 每项至少含 provider_code + media_id; 其余字段可选, 缺省时后端会再次拉取详情
    items: list


class CuratedMediaStatusSchema(BaseModel):
    ids: list
    status: int


class CuratedMediaCheckSchema(BaseModel):
    """批量校验可见性/可播放"""
    ids: list


class CuratedMediaCategorySchema(BaseModel):
    """批量设置分类(category_id 为空表示取消分类)"""
    ids: list
    category_id: Optional[int] = None


class CuratedMediaAutoCategorySchema(BaseModel):
    """按标题关键词自动归类未分类内容

    ids 为空时处理所有未分类内容; apply=False 只预览不写库。
    """
    ids: Optional[list] = None
    apply: bool = True


class SearchSchema(BaseModel):
    provider_code: str
    keyword: str
    page: int = 1
    page_size: int = 20


class ResolveSchema(BaseModel):
    provider_code: str
    url: str
