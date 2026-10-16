#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存注册与工厂。

根据 settings.CACHE_BACKEND 选择后端:
  - redis  (默认): RedisCache; 启动探活失败且开启 fallback 时自动退化为 MemoryCache
  - memory       : MemoryCache; 适合手机/个人单进程部署, 完全不需要 Redis

对外暴露:
  - registerCache(app) / registerRedis(app)  在 FastAPI 启动/关闭时装配缓存
  - create_cache()                           独立创建缓存实例(测试可用)
"""
from fastapi import FastAPI

from core.config import settings
from core.logger import logger
from .cache_base import BaseCache


def _new_memory_cache() -> 'BaseCache':
    from .cache_memory import MemoryCache
    return MemoryCache(
        max_entries=settings.MEMORY_CACHE_MAX_ENTRIES,
        sweep_interval=settings.MEMORY_CACHE_SWEEP_INTERVAL,
    )


async def create_cache() -> BaseCache:
    """按配置创建缓存后端实例。"""
    backend = (getattr(settings, 'CACHE_BACKEND', None) or 'redis').strip().lower()

    if backend == 'memory':
        cache = _new_memory_cache()
        await cache.start()
        logger.info('[cache] 使用内存缓存后端 (MemoryCache)')
        return cache

    from .cache_redis import RedisCache

    redis_cache = RedisCache(settings.getRedisURL())
    try:
        await redis_cache.ping()
        logger.info(
            f'[cache] 使用 Redis 缓存后端: '
            f'{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}'
        )
        return redis_cache
    except Exception as e:
        if getattr(settings, 'CACHE_FALLBACK_TO_MEMORY', False):
            logger.warning(f'[cache] Redis 连接失败({e}), 自动退化为内存缓存 (MemoryCache)')
            try:
                await redis_cache.close()
            except Exception:
                pass
            cache = _new_memory_cache()
            await cache.start()
            return cache
        await redis_cache.close()
        raise


def registerCache(app: FastAPI) -> None:
    """把缓存后端挂载到 app.state.cache (同时兼容旧的 app.state.redis)。"""

    @app.on_event('startup')
    async def cache_startup_event():
        app.state.cache = await create_cache()
        app.state.redis = app.state.cache  # 兼容仍读取 app.state.redis 的代码

    @app.on_event('shutdown')
    async def cache_shutdown_event():
        cache = getattr(app.state, 'cache', None)
        if cache is not None:
            try:
                await cache.close()
            except Exception as e:
                logger.warning(f'[cache] 关闭缓存后端失败: {e}')


# 兼容旧命名
registerRedis = registerCache
