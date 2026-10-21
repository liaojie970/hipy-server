#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : migrate_menu_meta.py
"""菜单顺序与名称梳理脚本(幂等)。

用法:
    cd app && python db/migrate_menu_meta.py                 # 使用应用配置中的数据库
    cd app && python db/migrate_menu_meta.py <db文件路径>     # sqlite: 指定 .db 文件路径

动作:
    1) 顶级目录排序调整为: 数据看板(前端固定路由, 不在库里)/海阔视界/视频源管理/精选内容/
       权限管理/系统管理/工具管理/系统监控;
    2) 二级菜单改名, 让菜单名"见文知义"(如 源管理 -> 源规则、配置中心 -> 参数配置), 统一不超过 4 个字。

只按 menu.name(二级) / path(一级) 匹配, 不改 path/component/permission, 因此不影响路由与权限。
可重复执行。
"""
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from core import constants  # noqa: E402
from core.config import settings  # noqa: E402

# 一级目录: (path, title, order_num)
PARENTS = [
    ('/hiker', '海阔视界', 1),
    ('/vod', '视频源管理', 2),
    ('/curated', '精选内容', 3),
    ('/permission', '权限管理', 4),
    ('/system', '系统管理', 5),
    ('/tool', '工具管理', 6),
    ('/monitor', '系统监控', 7),
]

# 二级菜单: (name, title)  只改名, 排序沿用原值
CHILDREN = [
    # 海阔视界
    ('HikerDeveloper', '开发者'),
    ('HikerRuleType', '规则分类'),
    ('HikerRule', '规则管理'),
    ('DeveloperDetail', '开发者'),
    ('RuleTypeDetail', '规则分类'),
    # 视频源管理
    ('VodRules', '源规则'),
    ('VodSubs', '订阅配置'),
    ('VodConfigs', '参数配置'),
    ('VodRulesEdit', '编辑源'),
    ('VodHouses', '上游仓库'),
    ('VodWeb', '效果预览'),
    # 精选内容
    ('CuratedProviders', '采集站点'),
    ('CuratedCategories', '内容分类'),
    ('CuratedMedia', '内容库'),
    ('CuratedImport', '搜索入库'),
    # 权限管理
    ('PermissionUser', '用户管理'),
    ('PermissionRole', '角色管理'),
    ('PermissionMenu', '菜单管理'),
    ('PermissionLabel', '接口权限'),
    # 系统管理
    ('SystemDictType', '字典管理'),
    ('SystemParameter', '参数管理'),
    ('ControlPanel', '数据维护'),
    # 工具管理
    ('Swagger', '接口文档'),
    ('liveTool', '直播源'),
    ('XfGpt', '讯飞星火'),
    # 系统监控
    ('Server', '服务监控'),
    ('Job', '定时任务'),
    ('JobLog', '执行日志'),
    ('LoginInfor', '登录日志'),
    ('Pip', '依赖包'),
    ('cacheList', '缓存列表'),
]


def _table() -> str:
    return f"{settings.SQL_TABLE_PREFIX}menus"


def _resolve_db_url(arg):
    """返回 SQLAlchemy URL; 传了 sqlite 文件路径则用它。"""
    if arg:
        arg = os.path.abspath(arg)
        if not os.path.exists(arg):
            raise SystemExit(f'数据库文件不存在: {arg}')
        return f'sqlite:///{arg}'
    return settings.getSqlalchemyURL()


def migrate(url: str) -> None:
    from sqlalchemy import create_engine, inspect, text

    table = _table()
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        if not insp.has_table(table):
            raise SystemExit(f'表 {table} 不存在, 请先初始化数据库')

        updated = 0
        with engine.begin() as conn:
            for path, title, order in PARENTS:
                res = conn.execute(
                    text(f'UPDATE {table} SET title=:t, order_num=:o WHERE path=:p AND parent_id=0'),
                    {'t': title, 'o': order, 'p': path})
                updated += res.rowcount or 0

            for name, title in CHILDREN:
                res = conn.execute(
                    text(f'UPDATE {table} SET title=:t WHERE name=:n'),
                    {'t': title, 'n': name})
                updated += res.rowcount or 0
        print(f'[{table}] 菜单顺序/名称同步完成, 影响 {updated} 行')

        # 复核输出
        with engine.connect() as conn:
            rows = conn.execute(text(
                f'SELECT id, parent_id, order_num, title FROM {table} '
                f'WHERE is_deleted=0 ORDER BY parent_id, order_num, id')).fetchall()
        parent_title = {r[0]: r[3] for r in rows if r[1] == 0}
        for r in rows:
            if r[1] == 0:
                print(f'  {r[2]}  {r[3]}')
            else:
                print(f'     {r[2]}  {r[3]}   <- {parent_title.get(r[1], r[1])}')
    finally:
        engine.dispose()


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    migrate(_resolve_db_url(arg))
    print('菜单整理完成')


if __name__ == '__main__':
    main()
