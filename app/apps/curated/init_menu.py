#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : init_menu.py
# 精选内容 - 后台菜单初始化(幂等, 每次启动调用)
"""
菜单是数据库驱动的, 这里保证【精选内容】相关菜单存在。
- 对超级管理员: 无需 role_menu 即可看到全部菜单;
- 对其他角色: 这里默认把菜单授予所有已存在角色, 可后续在"角色管理"里调整。
"""
from core.logger import logger
from db.session import SessionLocal
from apps.permission.models import Menus, Roles
from apps.permission.models.role import RoleMenu

# 默认站点(B站)预填的代理地址, 可按需在"站点管理"中修改
DEFAULT_PROXY = '127.0.0.1:7897'

# (name, path, component, title, icon, order_num)
CHILD_MENUS = [
    ('CuratedProviders', 'providers', '/curated/providers/index', '站点管理', 'international', 1),
    ('CuratedCategories', 'categories', '/curated/categories/index', '分类管理', 'tree', 2),
    ('CuratedMedia', 'media', '/curated/media/index', '内容库', 'list', 3),
    ('CuratedImport', 'import', '/curated/import/index', '搜索入库', 'search', 4),
]


def _ensure_menu(db, *, name, path, component, title, icon, order_num, parent_id):
    exist = db.query(Menus).filter(Menus.name == name, Menus.is_deleted == 0).first()
    if exist:
        return exist.id
    menu = Menus(path=path, component=component, is_frame=False, hidden=False, status=0,
                 order_num=order_num, name=name, title=title, icon=icon, no_cache=True,
                 parent_id=parent_id)
    db.add(menu)
    db.commit()
    db.refresh(menu)
    return menu.id


def init_curated_menus() -> None:
    db = SessionLocal()
    try:
        parent_id = _ensure_menu(db, name='Curated', path='/curated', component='',
                                 title='精选内容', icon='education', order_num=7, parent_id=0)
        menu_ids = [parent_id]
        for name, path, component, title, icon, order in CHILD_MENUS:
            menu_ids.append(_ensure_menu(db, name=name, path=path, component=component,
                                         title=title, icon=icon, order_num=order, parent_id=parent_id))
        # 授予所有角色
        role_ids = [r.id for r in db.query(Roles).filter(Roles.is_deleted == 0).all()]
        for mid in menu_ids:
            for rid in role_ids:
                exists = db.query(RoleMenu).filter(RoleMenu.role_id == rid,
                                                   RoleMenu.menu_id == mid,
                                                   RoleMenu.is_deleted == 0).first()
                if not exists:
                    db.add(RoleMenu(role_id=rid, menu_id=mid))
        db.commit()
        _ensure_default_provider(db)
    except Exception as e:  # noqa
        db.rollback()
        logger.warning(f'[curated] 初始化菜单失败: {e}')
    finally:
        db.close()


def _ensure_default_provider(db) -> None:
    """首次使用时放一个默认的 B站 站点配置, 便于在后台填 Cookie。

    同时会把默认代理预填进去(DEFAULT_PROXY); 对于已存在但还没配置代理的
    B站站点, 也做一次性补齐(仅当缺少 proxy 字段时)。
    """
    import json as _json
    from .models import CuratedProvider
    exist = db.query(CuratedProvider).filter(
        CuratedProvider.code == 'bilibili', CuratedProvider.is_deleted == 0).first()
    if not exist:
        db.add(CuratedProvider(name='哔哩哔哩', code='bilibili',
                               config=_json.dumps({'proxy': DEFAULT_PROXY}, ensure_ascii=False),
                               status=1, order_num=1,
                               remark='在"站点管理"中填入登录后的Cookie, 并确认网络代理可用'))
        db.commit()
        return
    # 已存在: 缺少 proxy 字段时补齐默认代理
    try:
        cfg = _json.loads(exist.config) if exist.config else {}
    except Exception:  # noqa
        cfg = None
    if isinstance(cfg, dict) and 'proxy' not in cfg:
        cfg['proxy'] = DEFAULT_PROXY
        exist.config = _json.dumps(cfg, ensure_ascii=False)
        db.commit()


if __name__ == '__main__':
    init_curated_menus()
    print('curated menus initialized')
