#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进程内内存缓存后端。

适用场景: 手机/个人单进程部署(uvicorn 单 worker / python main.py)。
特点:
  - 存储: dict[str, (bytes, expire_at)], 过期时间基于 time.monotonic()
  - 过期: 读时惰性淘汰 + 后台定时清理
  - 容量: 超过 max_entries 时优先淘汰最早过期的键(无过期视为最晚淘汰)
  - 返回 bytes, 与 RedisCache 行为一致

注意: 内存缓存仅在本进程内有效, 多 worker / 定时任务子进程不共享;
     进程重启后缓存清空(登录态会失效, 需重新登录)。
"""
import asyncio
import fnmatch
import os
import platform
import time
from typing import Any, Dict, List, Optional, Tuple

from core.logger import logger
from .cache_base import BaseCache, TTL, Value


class MemoryCache(BaseCache):
    """纯进程内缓存实现。"""

    def __init__(self, max_entries: int = 10000, sweep_interval: int = 60):
        self.max_entries = max(0, int(max_entries))
        self.sweep_interval = max(1, int(sweep_interval))
        # key -> (value_bytes, expire_at_monotonic or None)
        self._data: Dict[str, Tuple[bytes, Optional[float]]] = {}
        self._start_ts = time.time()
        self._sweeper: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ 内部工具
    @staticmethod
    def _key(key) -> str:
        """统一把 bytes/str 键归一化为 str, 兼容 redis 的 bytes 语义。"""
        if isinstance(key, bytes):
            return key.decode('utf-8')
        if isinstance(key, (bytearray, memoryview)):
            return bytes(key).decode('utf-8')
        return str(key)

    @staticmethod
    def _encode(value: Value) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, (bytearray, memoryview)):
            return bytes(value)
        return str(value).encode('utf-8')

    @staticmethod
    def _to_seconds(time_: Optional[TTL]) -> Optional[float]:
        if time_ is None:
            return None
        if hasattr(time_, 'total_seconds'):
            return float(time_.total_seconds())
        return float(time_)

    def _expire_at(self, time_: Optional[TTL]) -> Optional[float]:
        secs = self._to_seconds(time_)
        if secs is None:
            return None
        return time.monotonic() + secs

    def _get_raw(self, key: str) -> Optional[Tuple[bytes, Optional[float]]]:
        item = self._data.get(key)
        if item is None:
            return None
        _, expire_at = item
        if expire_at is not None and expire_at <= time.monotonic():
            self._data.pop(key, None)
            return None
        return item

    def _purge_expired(self) -> int:
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._data.items() if exp is not None and exp <= now]
        for k in expired:
            self._data.pop(k, None)
        return len(expired)

    def _evict_if_needed(self) -> None:
        if self.max_entries <= 0 or len(self._data) <= self.max_entries:
            return
        self._purge_expired()
        overflow = len(self._data) - self.max_entries
        if overflow <= 0:
            return

        def sort_key(item):
            _, exp = item[1]
            return exp if exp is not None else float('inf')

        for key, _ in sorted(self._data.items(), key=sort_key)[:overflow]:
            self._data.pop(key, None)
        logger.debug(f'[cache] MemoryCache 超过上限, 淘汰 {overflow} 个键')

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self.sweep_interval)
            try:
                removed = self._purge_expired()
                if removed:
                    logger.debug(f'[cache] MemoryCache 清理过期键 {removed} 个, 剩余 {len(self._data)}')
            except asyncio.CancelledError:
                raise
            except Exception as e:  # pragma: no cover
                logger.warning(f'[cache] MemoryCache 清理任务异常: {e}')

    # ------------------------------------------------------------------ 生命周期
    async def start(self) -> None:
        if self._sweeper is None:
            self._sweeper = asyncio.create_task(self._sweep_loop())

    async def close(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
            self._sweeper = None
        self._data.clear()

    # ------------------------------------------------------------------ 接口实现
    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Optional[bytes]:
        item = self._get_raw(self._key(key))
        return item[0] if item else None

    async def set(self, key: str, value: Value, ex: Optional[TTL] = None) -> bool:
        self._data[self._key(key)] = (self._encode(value), self._expire_at(ex))
        self._evict_if_needed()
        return True

    async def setex(self, key: str, time: TTL, value: Value) -> bool:
        return await self.set(key, value, ex=time)

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            key = self._key(key)
            if key in self._data:
                self._data.pop(key, None)
                count += 1
        return count

    async def exists(self, key: str) -> int:
        return 1 if self._get_raw(self._key(key)) else 0

    async def incr(self, key: str, amount: int = 1) -> int:
        key = self._key(key)
        item = self._get_raw(key)
        current = int(item[0]) if item else 0
        new_value = current + amount
        expire_at = item[1] if item else None  # incr 保留原有 TTL
        self._data[key] = (self._encode(new_value), expire_at)
        return new_value

    async def expire(self, key: str, time: TTL) -> bool:
        key = self._key(key)
        item = self._get_raw(key)
        if not item:
            return False
        self._data[key] = (item[0], self._expire_at(time))
        return True

    async def ttl(self, key: str) -> int:
        item = self._get_raw(self._key(key))
        if not item:
            return -2
        _, expire_at = item
        if expire_at is None:
            return -1
        return max(0, int(expire_at - time.monotonic()))

    async def keys(self, pattern: str = "*") -> List[bytes]:
        self._purge_expired()
        return [k.encode('utf-8') for k in list(self._data.keys())
                if fnmatch.fnmatchcase(k, pattern)]

    async def scan(self, cursor: int = 0, match: Optional[str] = None,
                   count: Optional[int] = None) -> Tuple[int, List[bytes]]:
        matched = await self.keys(match or '*')
        # 与 redis 语义对齐: 按 count 分批返回, 用 cursor 作为偏移量
        if count and count > 0:
            start = int(cursor or 0)
            chunk = matched[start:start + count]
            next_cursor = start + count if start + count < len(matched) else 0
            return next_cursor, chunk
        return 0, matched

    async def info(self, section: Optional[str] = None) -> Dict[str, Any]:
        if section == 'commandstats':
            return {}
        self._purge_expired()
        used = sum(len(value) for value, _ in self._data.values())
        uptime = int(time.time() - self._start_ts)
        used_human = f'{used / 1024:.2f}K'
        return {
            'redis_version': 'memcache-1.0',
            'redis_mode': 'standalone',
            'role': 'master',
            'backend': 'memory',
            'os': f'{platform.system()} {platform.release()}',
            'arch_bits': 64,
            'process_id': os.getpid(),
            'uptime_in_seconds': uptime,
            'uptime_in_days': uptime // 86400,
            'connected_clients': 1,
            'used_memory': used,
            'used_memory_human': used_human,
            'used_memory_peak_human': used_human,
            'db0': f'keys={len(self._data)},expires=0,avg_ttl=0',
        }

    async def dbsize(self) -> int:
        self._purge_expired()
        return len(self._data)

    async def flushdb(self) -> bool:
        self._data.clear()
        return True
