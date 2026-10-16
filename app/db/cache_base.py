#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存层统一接口。

设计目标: 抽象出项目实际用到的 Redis 操作, 提供两种后端:
  - RedisCache : 基于 redis.asyncio, 支持多进程/多机(默认)
  - MemoryCache: 纯进程内 dict 实现, 适合手机/个人单进程部署

接口签名刻意对齐 redis.asyncio.Redis, 现有调用点几乎无需修改:
  - get 返回 bytes(调用方会 .decode() / json.loads(bytes))
  - setex(key, time, value) 的 time 支持 int 秒或 timedelta
  - scan 返回 (cursor, [bytes_key, ...])
  - incr 对不存在的键从 0 开始累加(即首次返回 amount)
"""
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

# 可写入缓存的值类型
Value = Union[str, bytes, bytearray, memoryview, int, float]
# 过期时间: 秒(int/float) 或 timedelta
TTL = Union[int, float, timedelta]


class BaseCache(ABC):
    """异步缓存后端统一接口。"""

    async def start(self) -> None:
        """启动后端所需的后台任务(如内存清理), 默认无操作。"""

    @abstractmethod
    async def ping(self) -> bool:
        """探活, 成功返回 True。"""

    @abstractmethod
    async def get(self, key: str) -> Optional[bytes]:
        """取值, 不存在或已过期返回 None。"""

    @abstractmethod
    async def set(self, key: str, value: Value, ex: Optional[TTL] = None) -> bool:
        """设值, ex 可选过期时间。"""

    @abstractmethod
    async def setex(self, key: str, time: TTL, value: Value) -> bool:
        """设值并带过期时间(与 redis 参数顺序一致)。"""

    @abstractmethod
    async def delete(self, *keys: str) -> int:
        """删除一个或多个键, 返回实际删除数量。"""

    @abstractmethod
    async def exists(self, key: str) -> int:
        """是否存在(0/1)。"""

    @abstractmethod
    async def incr(self, key: str, amount: int = 1) -> int:
        """自增, 返回自增后的值。"""

    @abstractmethod
    async def expire(self, key: str, time: TTL) -> bool:
        """给已存在的键设置过期时间。"""

    @abstractmethod
    async def ttl(self, key: str) -> int:
        """剩余过期秒数: -1 无过期, -2 键不存在。"""

    @abstractmethod
    async def keys(self, pattern: str = "*") -> List[bytes]:
        """按 glob 匹配返回键列表(bytes)。"""

    @abstractmethod
    async def scan(self, cursor: int = 0, match: Optional[str] = None,
                   count: Optional[int] = None) -> Tuple[int, List[bytes]]:
        """游标扫描, 返回 (next_cursor, [bytes_key, ...])。"""

    @abstractmethod
    async def info(self, section: Optional[str] = None) -> Dict[str, Any]:
        """返回缓存状态信息字典。"""

    @abstractmethod
    async def dbsize(self) -> int:
        """键数量。"""

    @abstractmethod
    async def flushdb(self) -> bool:
        """清空当前库。"""

    async def close(self) -> None:
        """释放连接/后台资源, 默认无操作。"""
