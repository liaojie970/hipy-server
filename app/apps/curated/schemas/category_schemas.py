#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : category_schemas.py
from typing import Optional

from pydantic import BaseModel


class CuratedCategorySchema(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    status: Optional[int] = 1
    order_num: Optional[int] = 1
    keywords: Optional[str] = None
    is_default: Optional[int] = None
    remark: Optional[str] = None


class CuratedCategoryQuerySchema(BaseModel):
    keyword: Optional[str] = None
    status: Optional[int] = None
    page: int = 1
    page_size: int = 25
