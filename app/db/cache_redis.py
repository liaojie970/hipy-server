#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Redis 缓存后端: 对 redis.asyncio.Redis 的薄封装。"""
from typing import Any, Dict, List, Optional, Tuple

try:
    from redis import asyncio as aioredis
except ImportError:  # 兼容老版本依赖
    import aioredis

from core.logger import logger
from .cache_base import BaseCache, TTL, Value


class RedisCache(BaseCache):
    """基于 redis.asyncio 的缓存实现。"""

    def __init__(self, url: str, connect_timeout: int = 3, socket_timeout: int = 5):
        self.url = url
        self._client = aioredis.from_url(
            url,
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
        )

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def get(self, key: str) -> Optional[bytes]:
        return await self._client.get(key)

    async def set(self, key: str, value: Value, ex: Optional[TTL] = None) -> bool:
        return bool(await self._client.set(key, value, ex=ex))

    async def setex(self, key: str, time: TTL, value: Value) -> bool:
        return bool(await self._client.setex(key, time, value))

    async def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        return int(await self._client.delete(*keys))

    async def exists(self, key: str) -> int:
        return int(await self._client.exists(key))

    async def incr(self, key: str, amount: int = 1) -> int:
        return int(await self._client.incr(key, amount))

    async def expire(self, key: str, time: TTL) -> bool:
        return bool(await self._client.expire(key, time))

    async def ttl(self, key: str) -> int:
        return int(await self._client.ttl(key))

    async def keys(self, pattern: str = "*") -> List[bytes]:
        return await self._client.keys(pattern)

    async def scan(self, cursor: int = 0, match: Optional[str] = None,
                   count: Optional[int] = None) -> Tuple[int, List[bytes]]:
        return await self._client.scan(cursor=cursor, match=match, count=count)

    async def info(self, section: Optional[str] = None) -> Dict[str, Any]:
        return await self._client.info(section)

    async def dbsize(self) -> int:
        return int(await self._client.dbsize())

    async def flushdb(self) -> bool:
        return bool(await self._client.flushdb())

    async def close(self) -> None:
        try:
            await self._client.close()
        except Exception as e:  # pragma: no cover - 关闭失败不影响退出
            logger.warning(f'[cache] 关闭 Redis 连接失败: {e}')
