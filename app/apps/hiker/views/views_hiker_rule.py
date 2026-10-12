#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : views_hiker_rule.py
# Author: DaShenHan&道长-----先苦后甜，任凭晚风拂柳颜------
# Author's Blog: https://blog.csdn.net/qq_32394351
# Date  : 2023/12/3

from fastapi import APIRouter, Depends, Query, File, UploadFile
from sqlalchemy.orm import Session
from ...permission.models import Users
from ..schemas import rule_schemas
from ..curd.curd_hiker_rule import curd_hiker_rule as curd
from ..models.hiker_rule import HikerRuleType
from ..models.hiker_developer import HikerDeveloper

from common import deps, error_code, data_scope

from common.resp import respSuccessJson, respErrorJson

router = APIRouter()

access_name = 'hiker:rule'
api_url = '/hiker_rule'


def _scoped_get(curd, db: Session, _id: int, user):
    """按数据范围查单条规则(详情用); 显式带连表条件避免笛卡尔积, 查不到视为无权限/不存在。"""
    q = db.query(*curd.query_columns).filter(
        curd.model.id == _id, curd.model.is_deleted == 0,
        curd.model.dev_id == HikerDeveloper.id,
        curd.model.type_id == HikerRuleType.id)
    q = data_scope.apply_scope(q, curd.model, db, user)
    row = q.first()
    return dict(row) if row else {}


def _ensure_all_writable(curd, db: Session, ids, user) -> None:
    """批量预校验: 任一目标不可写则直接抛错(先校验, 后执行, 避免半成功)。"""
    for _id in ids:
        data_scope.ensure_writable(curd.get(db, _id=int(_id)), db, user)


@router.get(api_url, summary="搜索规则")
async def searchRecords(*,
                        db: Session = Depends(deps.get_db),
                        u: Users = Depends(deps.get_current_user),
                        name: str = Query(None),
                        author: str = Query(None),
                        value: str = Query(None),
                        url: str = Query(None),
                        dev_id: int = Query(None),
                        page: int = Query(1, gt=0),
                        page_size: int = Query(20, gt=0),
                        ):
    scope_filters = data_scope.apply_scope([], curd.model, db, u)
    res = curd.search(db, name=name, author=author, value=value, url=url, dev_id=dev_id, page=page,
                      page_size=page_size, extra_filters=scope_filters)
    return respSuccessJson(res)


@router.get(api_url + "/{_id}", summary="通过ID获取规则")
async def getRecord(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.get_current_user),
                    _id: int,
                    ):
    return respSuccessJson(_scoped_get(curd, db, _id, u))


@router.post(api_url, summary="添加规则")
async def addRecord(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.user_perm([f"{access_name}:post"])),
                    obj: rule_schemas.RuleSchema,
                    ):
    res = curd.create(db, obj_in=obj, creator_id=u['id'])
    if res:
        return respSuccessJson()
    return respErrorJson(error=error_code.ERROR_HIKER_RULE_TYPE_ADD_ERROR)


@router.put(api_url + "/{_id}", summary="修改规则")
async def setRecord(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.user_perm([f"{access_name}:put"])),
                    _id: int,
                    obj: rule_schemas.RuleSchema,
                    ):
    data_scope.ensure_writable(curd.get(db, _id=_id), db, u)
    curd.update(db, _id=_id, obj_in=obj, modifier_id=u['id'])
    return respSuccessJson()


@router.delete(api_url + "/{_ids}", summary="删除规则")
async def delRecord(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.user_perm([f"{access_name}:delete"])),
                    _ids: str,
                    ):
    _ids = list(map(lambda x: int(x), _ids.split(',')))
    _ensure_all_writable(curd, db, _ids, u)
    curd.deletes(db, _ids=_ids, deleter_id=u['id'])
    return respSuccessJson()
