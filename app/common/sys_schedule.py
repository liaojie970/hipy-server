#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : sys_schedule.py
# Author: DaShenHan&道长-----先苦后甜，任凭晚风拂柳颜------
# Author's Blog: https://blog.csdn.net/qq_32394351
# Date  : 2023/12/10
from apscheduler.executors.pool import ProcessPoolExecutor, ThreadPoolExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from core.config import settings


class ScheduleCli(object):
    _instance = None

    def __new__(cls, *args, **kw):
        if cls._instance is None:
            cls._instance = object.__new__(cls, *args, **kw)
        return cls._instance

    def __init__(self):
        # 对象 在 @app.on_event("startup") 中初始化
        self._schedule = None
        # 进程池大小: 默认 10, 手机/小内存设备可配小一点以节省内存
        try:
            self.pool_size = max(1, int(getattr(settings, 'SCHEDULER_POOL_SIZE', 10) or 10))
        except (TypeError, ValueError):
            self.pool_size = 10
        # 执行器类型: process=进程池(默认, 旧行为) / thread=线程池
        #   进程池每次跑任务都会 fork 子进程, 子进程继承监听 socket 且常驻内存;
        #   父进程死掉后端口被这些子进程占着但不再 accept -> 整个后端“假死”。
        #   手机/小内存部署建议 SCHEDULER_EXECUTOR=thread
        executor_type = str(getattr(settings, 'SCHEDULER_EXECUTOR', 'process') or 'process').strip().lower()
        if executor_type in ('thread', 'threads', 'threadpool', 'thread_pool'):
            self.executor_type = 'thread'
        else:
            self.executor_type = 'process'

    def init_scheduler(self) -> None:
        """
        初始化 apscheduler
        :return:
        """
        interval_task = {
            # 配置存储器 |不配置了，手写一个job表
            # "jobstores": {
            #     'default': SQLAlchemyJobStore(url=settings.getSqlalchemyURL())
            # },
            # 配置执行器
            "executors": {
                # 进程池: 每个任务 fork 一个子进程(会继承监听 socket, 小内存设备慎用)
                # 线程池: 任务在进程内线程里跑, 不 fork, 后端主进程死了端口立刻释放
                'default': (ThreadPoolExecutor(self.pool_size)
                            if self.executor_type == 'thread'
                            else ProcessPoolExecutor(self.pool_size))
            },
            # 创建job时的默认参数
            "job_defaults": {
                'coalesce': False,  # 是否合并执行
                'max_instances': 3,  # 最大实例数
            }

        }
        # job_stores = {'default': SQLAlchemyJobStore(url=settings.getSqlalchemyURL())}
        # self._schedule = AsyncIOScheduler(jobstores=job_stores)

        self._schedule = AsyncIOScheduler(**interval_task)
        self._schedule.start()

    # 使实例化后的对象 赋予apscheduler对象的方法和属性
    def __getattr__(self, name):
        return getattr(self._schedule, name)

    def __getitem__(self, name):
        return self._schedule[name]

    def __setitem__(self, name, value):
        self._schedule[name] = value

    def __delitem__(self, name):
        del self._schedule[name]


# 创建schedule对象
scheduler: AsyncIOScheduler = ScheduleCli()  # noqa

# 只允许导出 scheduler 实例化对象
__all__ = ["scheduler"]
