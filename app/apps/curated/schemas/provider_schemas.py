#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : provider_schemas.py
from typing import Optional, Union

from pydantic import BaseModel


class CuratedProviderSchema(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    # 允许传 dict 或 json 字符串; service 会统一序列化为字符串入库
    config: Optional[Union[dict, str]] = None
    status: Optional[int] = 1
    order_num: Optional[int] = 1
    remark: Optional[str] = None


class CuratedProviderQuerySchema(BaseModel):
    keyword: Optional[str] = None
    status: Optional[int] = None
    page: int = 1
    page_size: int = 25


class ProviderTestSchema(BaseModel):
    """测试站点配置(可直接传 config 而不入库)"""
    code: str
    config: Optional[Union[dict, str]] = None
