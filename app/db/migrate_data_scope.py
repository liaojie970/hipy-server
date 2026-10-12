#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : migrate_data_scope.py
"""角色数据范围(data_scope)字段迁移脚本(幂等)。

用法:
    python migrate_data_scope.py                # 使用应用配置中的数据库
    python migrate_data_scope.py <db文件路径>    # sqlite: 指定 .db 文件路径

动作:
    1) 若 t_roles 不存在 data_scope 列, 则 ALTER TABLE ADD COLUMN(默认 2);
    2) admin -> 3; general / Operation -> 2。

可重复执行, 不会报错。兼容 sqlite(通过 PRAGMA table_info 判断列是否存在)。
"""
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from core import constants  # noqa: E402
from core.config import settings  # noqa: E402

DEFAULT_SCOPE = 2
COLUMN = 'data_scope'


def _table() -> str:
    return f"{settings.SQL_TABLE_PREFIX}roles"


def _alter_sql(table: str) -> str:
    return f"ALTER TABLE {table} ADD COLUMN {COLUMN} INTEGER NOT NULL DEFAULT {DEFAULT_SCOPE}"


def _update_sqls(table: str, quote: str = '') -> list:
    """返回 [UPDATE admin, UPDATE general/Operation] 的 SQL 列表。

    :param quote: `key` 列的引用符(sqlite 可空, mysql 用反引号, pg 用双引号)
    """
    key_col = f"{quote}key{quote}" if quote else 'key'
    return [
        f"UPDATE {table} SET {COLUMN}=3 WHERE {key_col}='admin'",
        f"UPDATE {table} SET {COLUMN}=2 WHERE {key_col} IN ('general', 'Operation')",
    ]


def _resolve_sqlite_path(arg) -> str:
    """确定 sqlite 数据库文件路径; 非 sqlite 或无法确定时返回 None。"""
    if arg:
        return arg
    if settings.SQLALCHEMY_ENGINE == 'sqlite':
        return os.path.join(constants.BASE_DIR, f'db/{settings.SQL_DATABASE}.db')
    return None


def _has_column_sqlite(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def migrate_sqlite(path: str) -> None:
    """sqlite: 用 PRAGMA 判断列是否存在, 不存在才 ALTER。"""
    import sqlite3
    table = _table()
    conn = sqlite3.connect(path)
    try:
        if not _has_column_sqlite(conn, table, COLUMN):
            conn.execute(_alter_sql(table))
            print(f'[{table}] 已新增列 {COLUMN}(默认 {DEFAULT_SCOPE})')
        for sql in _update_sqls(table):
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def migrate_sqlalchemy(url: str) -> None:
    """非 sqlite: 用 SQLAlchemy inspector 判断列是否存在。"""
    from sqlalchemy import create_engine, inspect, text
    table = _table()
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        if not insp.has_table(table):
            raise SystemExit(f'表 {table} 不存在, 请先初始化数据库')
        exists = {c['name'] for c in insp.get_columns(table)}
        dialect = engine.dialect.name
        quote = '`' if dialect == 'mysql' else ('"' if dialect == 'postgresql' else '')
        with engine.begin() as conn:
            if COLUMN not in exists:
                conn.execute(text(_alter_sql(table)))
                print(f'[{table}] 已新增列 {COLUMN}(默认 {DEFAULT_SCOPE})')
            for sql in _update_sqls(table, quote):
                conn.execute(text(sql))
    finally:
        engine.dispose()


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    path = _resolve_sqlite_path(arg)
    if path:
        migrate_sqlite(path)
    else:
        migrate_sqlalchemy(settings.getSqlalchemyURL())
    print('数据范围(data_scope)迁移完成')


if __name__ == '__main__':
    main()
