#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : init_source.py
# 精选内容 - 运行时源规则初始化(幂等, 每次启动调用)
"""
保证 t4/spiders/亲子精选.py 作为一条启用规则存在于 t_vod_rules。

只有注册为规则后, /config 生成 TVBox 配置时才会把【亲子精选】放进 sites,
儿童专用订阅(sub=qinzi01, reg=亲子精选)才能过滤出唯一源。
"""
from core.logger import logger
from db.session import SessionLocal

RULE_NAME = '亲子精选'
RULE_GROUP = 't4/spiders'
RULE_FILE_TYPE = '.py'
RULE_PATH = 't4/spiders/亲子精选.py'


def init_curated_source() -> None:
    from apps.vod.curd.curd_rules import curd_vod_rules
    db = SessionLocal()
    try:
        rec = curd_vod_rules.getByName(db, RULE_NAME, RULE_FILE_TYPE, RULE_GROUP)
        if rec:
            fix = {}
            if not rec.is_exist:
                fix['is_exist'] = True
            if rec.status != 1:
                fix['status'] = 1
            if not rec.active:
                fix['active'] = True
            if fix:
                curd_vod_rules.update(db, _id=rec.id, obj_in=fix)
            return
        order_num = curd_vod_rules.get_max_order_num(db) + 1
        curd_vod_rules.create(db, obj_in={
            'name': RULE_NAME,
            'group': RULE_GROUP,
            'path': RULE_PATH,
            'file_type': RULE_FILE_TYPE,
            'is_exist': True,
            'status': 1,
            'active': True,
            'searchable': 1,
            'quickSearch': 0,
            'filterable': 1,
            'order_num': order_num,
            'ext': '',
        })
    except Exception as e:  # noqa
        logger.warning(f'[curated] 初始化精选源规则失败: {e}')
    finally:
        db.close()


if __name__ == '__main__':
    init_curated_source()
    print('curated source initialized')
