#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直播源聚合功能的数据库迁移(幂等)。

作用:
    1) 确保定时任务 live_source 存在(默认启用, 每天 03:30 跑一次)
    2) 把直播配置切到聚合产物 m3u/live_merged.m3u
       - 只在当前值是空 / txt/mytv.txt / mytv.txt 时才改
       - 需要强制覆盖时加 --force-config

用法:
    cd app && python db/migrate_live_source.py
    cd app && python db/migrate_live_source.py --db /path/to/hipy.db
    cd app && python db/migrate_live_source.py --keep-config
    cd app && python db/migrate_live_source.py --force-config

说明:
    手机端数据库是 SQLite, 本脚本只依赖标准库, 不导入项目依赖,
    因此即使后端没启动、虚拟环境没激活也能执行。
"""
import argparse
import os
import sqlite3
from datetime import datetime, timedelta

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(APP_DIR, 'db', 'hipy.db')

JOB_ID = 'live_source'
JOB_NAME = '直播源聚合'
JOB_FUNC = 'tasks.live_source.main'
CRON = '0 30 3 * * ?'
LIVE_M3U = 'm3u/live_merged.m3u'
OLD_LIVE_FILES = ('', 'txt/mytv.txt', 'mytv.txt')


def next_daily_run(hour=3, minute=30):
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.strftime('%Y-%m-%d %H:%M:%S')


def ensure_job(conn, enable=True):
    row = conn.execute(
        "SELECT id FROM t_job WHERE job_id=? AND is_deleted=0", (JOB_ID,)
    ).fetchone()

    if row:
        job_pk = row[0]
        conn.execute(
            """
            UPDATE t_job
               SET job_name=?, job_group=?, func_name=?, func_args=?, func_kwargs=?,
                   cron_model=?, coalesce=?, next_run=?, cron_expression=?, status=?, misfire_policy=?, active=?,
                   modified_time=CURRENT_TIMESTAMP
             WHERE id=?
            """,
            (JOB_NAME, 'setInterval', JOB_FUNC, '[]', '{}', 'cron', 1, next_daily_run(), CRON,
             1 if enable else 0, 2, 1 if enable else 0, job_pk),
        )
        print(f'[job] live_source 已存在, 已更新 (id={job_pk}, next_run={next_daily_run()}, active={bool(enable)})')
        return job_pk

    # 优先使用 17 (与 init_data/job.csv 对齐); 被占用则取 max(id)+1
    occupied = conn.execute("SELECT 1 FROM t_job WHERE id=17").fetchone()
    if occupied:
        job_pk = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM t_job").fetchone()[0]
    else:
        job_pk = 17

    conn.execute(
        """
        INSERT INTO t_job
            (id, job_id, job_name, job_group, func_name, func_args, func_kwargs,
             cron_model, coalesce, next_run, cron_expression, status, misfire_policy, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_pk, JOB_ID, JOB_NAME, 'setInterval', JOB_FUNC, '[]', '{}',
         'cron', 1, next_daily_run(), CRON, 1 if enable else 0, 2, 1 if enable else 0),
    )
    print(f'[job] 已新增 live_source (id={job_pk}, next_run={next_daily_run()}, active={bool(enable)})')
    return job_pk


def ensure_config(conn, force_config=False, keep_config=False):
    if keep_config:
        print('[config] --keep-config, 跳过直播配置切换')
        return

    use_row = conn.execute(
        "SELECT value FROM t_vod_configs WHERE key='vod_zb_use' AND is_deleted=0"
    ).fetchone()
    if use_row:
        if use_row[0] != 'file':
            conn.execute(
                "UPDATE t_vod_configs SET value='file', modified_time=CURRENT_TIMESTAMP "
                "WHERE key='vod_zb_use' AND is_deleted=0"
            )
            print(f'[config] vod_zb_use: {use_row[0]!r} -> file')
    else:
        conn.execute(
            "INSERT INTO t_vod_configs (name, key, value, value_type, remark, status, order_num) "
            "VALUES ('自动直播使用', 'vod_zb_use', 'file', 'str', 'file:使用文件,url:使用链接', 1, 11)"
        )
        print('[config] 新增 vod_zb_use=file')

    file_row = conn.execute(
        "SELECT value FROM t_vod_configs WHERE key='vod_zb_file' AND is_deleted=0"
    ).fetchone()
    if file_row:
        old_value = file_row[0] or ''
        if force_config or old_value in OLD_LIVE_FILES:
            conn.execute(
                "UPDATE t_vod_configs SET value=?, modified_time=CURRENT_TIMESTAMP "
                "WHERE key='vod_zb_file' AND is_deleted=0",
                (LIVE_M3U,),
            )
            print(f'[config] vod_zb_file: {old_value!r} -> {LIVE_M3U!r}')
        else:
            print(f'[config] vod_zb_file 已是 {old_value!r}, 保持不变 (需要覆盖加 --force-config)')
    else:
        conn.execute(
            "INSERT INTO t_vod_configs (name, key, value, value_type, remark, status, order_num) "
            "VALUES ('自动直播配置文件', 'vod_zb_file', ?, 'file', '直播源文件', 1, 10)",
            (LIVE_M3U,),
        )
        print(f'[config] 新增 vod_zb_file={LIVE_M3U!r}')


def main():
    parser = argparse.ArgumentParser(description='直播源聚合数据库迁移')
    parser.add_argument('--db', default=DEFAULT_DB, help='SQLite 数据库路径')
    parser.add_argument('--force-config', action='store_true', help='强制把 vod_zb_file 改为 m3u/live_merged.m3u')
    parser.add_argument('--keep-config', action='store_true', help='不改 vod_zb_use / vod_zb_file')
    parser.add_argument('--disable', action='store_true', help='只维护任务记录, 但设为暂停')
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f'数据库不存在: {args.db}')

    conn = sqlite3.connect(args.db)
    try:
        ensure_job(conn, enable=not args.disable)
        ensure_config(conn, force_config=args.force_config, keep_config=args.keep_config)
        conn.commit()
    finally:
        conn.close()

    print('[done] 直播源迁移完成, 重启后端后定时任务会按 cron 自动调度')


if __name__ == '__main__':
    main()
