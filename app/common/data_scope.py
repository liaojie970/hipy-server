#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : data_scope.py
"""行级数据范围(数据权限)统一工具。

数据范围三档(存于角色 t_roles.data_scope):
    1 = 仅本人(只看/只改自己创建的)
    2 = 本人 + 公共可读(公共 = creator_id 为 0/1, 公共记录只读)
    3 = 全部(不隔离)

公共可读: creator_id 为 0(系统内置) 或 1(超管 admin)。
"""
from typing import Optional

from sqlalchemy import func, or_

from apps.permission.models import Roles
from apps.permission.models.user import UserRole
from common import exceptions

# 0=系统内置, 1=超管
PUBLIC_READ_CREATOR_IDS = (0, 1)


def _user_id(user) -> Optional[int]:
    return user.get('id') if isinstance(user, dict) else getattr(user, 'id', None)


def user_scope(db, user) -> int:
    """取用户所有角色 data_scope 的最大值。

    - 超管(is_superuser)直接返回 3;
    - 角色从数据库关联表(t_user_role)解析, 不依赖 user 字典里的 'roles' 键
      (get_current_user 返回的是列字典, 不含 roles);
    - 无角色时按最严档位 1 处理。
    """
    if not user:
        return 1
    is_superuser = user.get('is_superuser') if isinstance(user, dict) else getattr(user, 'is_superuser', False)
    if is_superuser:
        return 3
    user_id = _user_id(user)
    if user_id is None:
        return 1
    role_ids = [r[0] for r in db.query(UserRole.role_id).filter(
        UserRole.user_id == user_id, UserRole.is_deleted == 0).all()]
    if not role_ids:
        return 1
    scope = db.query(func.max(Roles.data_scope)).filter(
        Roles.id.in_(role_ids), Roles.is_deleted == 0).scalar()
    return int(scope) if scope else 1


def _scope_condition(model, db, user):
    """返回需要追加的过滤条件; scope=3 时返回 None(不过滤)。"""
    scope = user_scope(db, user)
    if scope >= 3:
        return None
    user_id = _user_id(user)
    if scope == 2:
        return or_(model.creator_id == user_id,
                   model.creator_id.in_(PUBLIC_READ_CREATOR_IDS))
    return model.creator_id == user_id


def apply_scope(query, model, db, user):
    """对查询追加数据范围条件。

    query 既可以是 SQLAlchemy Query(返回追加条件后的新 Query),
    也可以是过滤器 list(返回追加条件后的新 list), 以适配项目的 filters 写法。
    scope=3 时原样返回, 不追加任何条件。
    """
    cond = _scope_condition(model, db, user)
    if cond is None:
        return query
    if isinstance(query, (list, tuple)):
        return list(query) + [cond]
    return query.filter(cond)


def ensure_writable(obj, db, user) -> None:
    """校验 obj 是否可被 user 修改/删除; 不可写时抛 UserPermError。

    - scope=3(全部)直接通过;
    - 否则 obj 为空, 或 obj.creator_id 不等于当前用户 id 时拒绝。
    - 档位 2 的公共记录(creator_id 0/1)只能读, 会在此被拒绝。
    """
    if user_scope(db, user) >= 3:
        return
    user_id = _user_id(user)
    creator_id = obj.get('creator_id') if isinstance(obj, dict) else getattr(obj, 'creator_id', None)
    if obj is None or creator_id != user_id:
        raise exceptions.UserPermError()


def ensure_visible(obj, db, user) -> None:
    """校验 obj 对 user 是否可见(只读语义); 不可见时抛 UserPermError。

    可见规则与 apply_scope 的读范围一致:
    - scope=3(全部)全部可见;
    - scope=2 本人 + 公共(creator_id 0/1)可见;
    - scope=1 仅本人可见。
    """
    if obj is None:
        raise exceptions.UserPermError()
    scope = user_scope(db, user)
    if scope >= 3:
        return
    user_id = _user_id(user)
    creator_id = obj.get('creator_id') if isinstance(obj, dict) else getattr(obj, 'creator_id', None)
    if creator_id == user_id:
        return
    if scope == 2 and creator_id in PUBLIC_READ_CREATOR_IDS:
        return
    raise exceptions.UserPermError()
