#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直播线路体检定时任务的数据库迁移（幂等）。

作用:
    1) 确保定时任务 live_check 存在（默认每 6 小时复查一次已生成的 m3u）；
    2) 不动现有 live_source（每天 03:30 重建）任务，两者职责分离：
         live_source -> 拉上游 + 测活 + 去重 + 重建 m3u
         live_check  -> 只对现有 m3u 复查，把新判死的线路剔掉
    3) 台账/阈值等参数在 t4/files/json/live_sources.json 的 health 段里改，
       本脚本不碰该文件。

用法（只依赖标准库，手机端也能直接跑）:
    cd app && python db/migrate_live_health.py
    cd app && python db/migrate_live_health.py --db /path/to/hipy.db
    cd app && python db/migrate_live_health.py --cron "0 0 0/3 * * ?"   # 例：每 3 小时复查一次
    cd app && python db/migrate_live_health.py --disable
"""
import argparse
import os
import sqlite3
from datetime import datetime, timedelta

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(APP_DIR, 'db', 'hipy.db')

JOB_ID = 'live_check'
JOB_NAME = '直播线路复查'
JOB_FUNC = 'tasks.live_health.main'
DEFAULT_CRON = '0 0 0/6 * * ?'   # 每 6 小时
PREFERRED_PK = 18


def _parse_cron_hours(cron):
    """从 '0 0 0/6 * * ?' 里推出下次执行时间，只在最后一个字段是 simple 表达式时猜。"""
    try:
        fields = cron.split()
        minute = int(fields[1]) if fields[1] not in ('*', '?') else 0
        hour_field = fields[2]
        if hour_field.startswith('0/'):
            step = int(hour_field.split('/')[1])
            hours = list(range(0, 24, max(1, step)))
        elif hour_field == '*':
            hours = list(range(24))
        else:
            hours = [int(hour_field)]
    except Exception:  # noqa
        minute, hours = 0, [0]
    now = datetime.now()
    for day in (0, 1):
        base = now + timedelta(days=day)
        for h in hours:
            target = base.replace(hour=h, minute=minute, second=0, microsecond=0)
            if target > now:
                return target.strftime('%Y-%m-%d %H:%M:%S')
    return (now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')


def ensure_job(conn, cron=DEFAULT_CRON, enable=True):
    next_run = _parse_cron_hours(cron)
    row = conn.execute(
        "SELECT id FROM t_job WHERE job_id=? AND is_deleted=0", (JOB_ID,)
    ).fetchone()

    if row:
        pk = row[0]
        conn.execute(
            """
            UPDATE t_job
               SET job_name=?, job_group=?, func_name=?, func_args=?, func_kwargs=?,
                   cron_model=?, coalesce=?, next_run=?, cron_expression=?, status=?,
                   misfire_policy=?, active=?, modified_time=CURRENT_TIMESTAMP
             WHERE id=?
            """,
            (JOB_NAME, 'setInterval', JOB_FUNC, '[]', '{}', 'cron', 1, next_run, cron,
             1 if enable else 0, 2, 1 if enable else 0, pk),
        )
        print(f'[job] {JOB_ID} 已存在, 已更新 (id={pk}, next_run={next_run}, active={bool(enable)})')
        return pk

    occupied = conn.execute("SELECT 1 FROM t_job WHERE id=?", (PREFERRED_PK,)).fetchone()
    pk = PREFERRED_PK if not occupied else conn.execute(
        "SELECT COALESCE(MAX(id), 0) + 1 FROM t_job").fetchone()[0]
    conn.execute(
        """
        INSERT INTO t_job
            (id, job_id, job_name, job_group, func_name, func_args, func_kwargs,
             cron_model, coalesce, next_run, cron_expression, status, misfire_policy, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (pk, JOB_ID, JOB_NAME, 'setInterval', JOB_FUNC, '[]', '{}',
         'cron', 1, next_run, cron, 1 if enable else 0, 2, 1 if enable else 0),
    )
    print(f'[job] 已新增 {JOB_ID} (id={pk}, next_run={next_run}, active={bool(enable)})')
    return pk


def main():
    parser = argparse.ArgumentParser(description='直播线路体检定时任务迁移')
    parser.add_argument('--db', default=DEFAULT_DB, help='SQLite 数据库路径')
    parser.add_argument('--cron', default=DEFAULT_CRON, help=f'cron 表达式, 默认 "{DEFAULT_CRON}"')
    parser.add_argument('--disable', action='store_true', help='只维护任务记录, 但设为暂停')
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f'数据库不存在: {args.db}')

    conn = sqlite3.connect(args.db)
    try:
        ensure_job(conn, cron=args.cron, enable=not args.disable)
        conn.commit()
        rows = conn.execute(
            "SELECT id, job_id, job_name, cron_expression, active FROM t_job WHERE is_deleted=0 ORDER BY id"
        ).fetchall()
        print('\n当前定时任务:')
        for r in rows:
            print(f'  id={r[0]:<3} {r[1]:<12} {r[2]:<10} cron={r[3]:<16} active={r[4]}')
    finally:
        conn.close()
    print('\n提示: 重启后端或等调度器刷新后，新任务才会进入 APScheduler。')
    print('     先手动验证一次: cd app && python -m tasks.live_health --dry-run --limit 60')


if __name__ == '__main__':
    main()
