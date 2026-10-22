#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : migrate_git_house.py
"""上游仓库地址迁移脚本(幂等)。

背景:
    「上游仓库」列表里的「链接」= 参数配置 vod_git_proxy(加速前缀) + github raw 地址。
    ① 默认加速前缀 https://ghproxy.liuzhicong.com/ 已失效 -> 换成实测可用的 https://gh-proxy.com/
    ② 默认仓库 heroaku/TVboxo 已 404 -> 换成 qist/tvbox|js
    ③ 中间的过渡默认值 gitee:liaoj/dr_py|js 所在的 gitee 仓库已被下架(HTTP 451/violation)
       -> 回退到原 github 仓库 hjdhnx/dr_py|js(靠加速前缀下载)

用法:
    cd app && python db/migrate_git_house.py                # 使用应用配置中的数据库
    cd app && python db/migrate_git_house.py <db文件路径>    # sqlite: 指定 .db 文件路径

动作(只在仍是老默认值时才改, 用户自己改过的不动):
    1) vod_drpy_house1 = 'gitee:liaoj/dr_py|js' -> 'hjdhnx/dr_py|js'
    2) vod_drpy_house2 = 'heroaku/TVboxo|Js'    -> 'qist/tvbox|js'
    3) vod_git_proxy  为已失效的 liuzhicong 前缀 或 空(过渡默认值) -> 'https://gh-proxy.com/'

改完到「上游仓库」点一次「获取仓库数据」即可刷新列表里的链接。
可重复执行。
"""
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from core import constants  # noqa: E402
from core.config import settings  # noqa: E402

DEFAULT_GIT_PROXY = 'https://gh-proxy.com/'

# (key, 老值, 新值)
MIGRATIONS = [
    ('vod_drpy_house1', 'gitee:liaoj/dr_py|js', 'hjdhnx/dr_py|js'),
    ('vod_drpy_house2', 'heroaku/TVboxo|Js', 'qist/tvbox|js'),
    ('vod_git_proxy', 'https://ghproxy.liuzhicong.com/', DEFAULT_GIT_PROXY),
    ('vod_git_proxy', 'https://n.liuzhicong.com/', DEFAULT_GIT_PROXY),
    # 空值 = 曾经迁移到「直连」的过渡默认值; 国内直连 raw.githubusercontent.com 基本不通
    ('vod_git_proxy', '', DEFAULT_GIT_PROXY),
]


def _table() -> str:
    return f"{settings.SQL_TABLE_PREFIX}vod_configs"


def _resolve_sqlite_path(arg) -> str:
    """确定 sqlite 数据库文件路径; 非 sqlite 或无法确定时返回 None。"""
    if arg:
        return arg
    if settings.SQLALCHEMY_ENGINE == 'sqlite':
        return os.path.join(constants.BASE_DIR, f'db/{settings.SQL_DATABASE}.db')
    return None


def _apply(executor, placeholder: str = '?', quote: str = '') -> None:
    """按 MIGRATIONS 执行 UPDATE。

    :param executor: executor(sql, params) -> 影响行数, 由调用方提供
    :param placeholder: sqlite 用 '?', 其他方言用命名参数 ':new' 之类
    :param quote: key/value 列的引用符(sqlite 可空, mysql 用反引号, pg 用双引号)
    """
    table = _table()
    key_col = f'{quote}key{quote}' if quote else 'key'
    value_col = f'{quote}value{quote}' if quote else 'value'
    for key, old_value, new_value in MIGRATIONS:
        if placeholder == '?':
            sql = f"UPDATE {table} SET {value_col}=? WHERE {key_col}=? AND {value_col}=?"
            params = (new_value, key, old_value)
        else:
            sql = f"UPDATE {table} SET {value_col}=:new WHERE {key_col}=:key AND {value_col}=:old"
            params = {'new': new_value, 'key': key, 'old': old_value}
        if executor(sql, params):
            print(f'[{table}] {key}: {old_value!r} -> {new_value!r}')


def migrate_sqlite(path: str) -> None:
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        def executor(sql, params):
            return conn.execute(sql, params).rowcount

        _apply(executor)
        conn.commit()
    finally:
        conn.close()


def migrate_sqlalchemy(url: str) -> None:
    from sqlalchemy import create_engine, inspect, text
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        if not insp.has_table(_table()):
            raise SystemExit(f'表 {_table()} 不存在, 请先初始化数据库')
        dialect = engine.dialect.name
        quote = '`' if dialect == 'mysql' else ('"' if dialect == 'postgresql' else '')
        with engine.begin() as conn:
            def executor(sql, params):
                return conn.execute(text(sql), params).rowcount

            _apply(executor, placeholder=':new', quote=quote)
    finally:
        engine.dispose()


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    path = _resolve_sqlite_path(arg)
    if path:
        migrate_sqlite(path)
    else:
        migrate_sqlalchemy(settings.getSqlalchemyURL())
    print('上游仓库地址迁移完成, 请到「上游仓库」点一次「获取仓库数据」刷新链接')


if __name__ == '__main__':
    main()
