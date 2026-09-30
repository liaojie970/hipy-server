#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : registry.py
# 精选内容 - 站点适配器注册表
from typing import Dict, Optional, Type

from .base import BaseProvider
from .bilibili import BilibiliProvider

# 站点编码 -> 适配器类
PROVIDERS: Dict[str, Type[BaseProvider]] = {
    BilibiliProvider.code: BilibiliProvider,
}


def get_provider(code: str, config: Optional[dict] = None) -> Optional[BaseProvider]:
    cls = PROVIDERS.get(code)
    if not cls:
        return None
    return cls(config)


def list_providers():
    return [{"code": cls.code, "name": cls.name, "need_login": cls.need_login}
            for cls in PROVIDERS.values()]
