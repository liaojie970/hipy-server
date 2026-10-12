#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : views_hiker_developer.py
# Author: DaShenHan&道长-----先苦后甜，任凭晚风拂柳颜------
# Author's Blog: https://blog.csdn.net/qq_32394351
# Date  : 2023/12/3

from fastapi import APIRouter, Depends, Query, File, UploadFile
from sqlalchemy.orm import Session
from ...permission.models import Users
from ..schemas import developer_schemas
from ..schemas.common import ActiveSchema
from ..curd.curd_hiker_developer import curd_hiker_developer as curd

from common import deps, error_code, data_scope

from common.resp import respSuccessJson, respErrorJson

router = APIRouter()

access_name = 'hiker:developer'
api_url = '/hiker_developer'


def _scoped_get(curd, db: Session, _id: int, user, to_dict: bool = True):
    """按数据范围查单条记录(详情用); 查不到即视为无权限/不存在。"""
    q = db.query(*curd.query_columns).filter(
        curd.model.id == _id, curd.model.is_deleted == 0)
    q = data_scope.apply_scope(q, curd.model, db, user)
    row = q.first()
    if not to_dict:
        return row
    return dict(row) if row else {}


def _ensure_all_writable(curd, db: Session, ids, user) -> None:
    """批量预校验: 任一目标不可写则直接抛错(先校验, 后执行, 避免半成功)。"""
    for _id in ids:
        data_scope.ensure_writable(curd.get(db, _id=int(_id)), db, user)


@router.get(api_url, summary="搜索开发者")
async def searchRecords(*,
                        db: Session = Depends(deps.get_db),
                        u: Users = Depends(deps.get_current_user),
                        status: int = Query(None),
                        name: str = Query(None),
                        qq: str = Query(None),
                        page: int = Query(1, gt=0),
                        page_size: int = Query(20, gt=0),
                        ):
    scope_filters = data_scope.apply_scope([], curd.model, db, u)
    res = curd.search(db, name=name, qq=qq, status=status, page=page, page_size=page_size,
                      extra_filters=scope_filters)
    return respSuccessJson(res)


@router.get(api_url + "/{_id}", summary="通过ID获取开发者信息")
async def getRecord(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.get_current_user),
                    _id: int,
                    ):
    return respSuccessJson(_scoped_get(curd, db, _id, u))


@router.post(api_url, summary="添加开发者")
async def addRecord(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.user_perm([f"{access_name}:post"])),
                    obj: developer_schemas.DeveloperSchema,
                    ):
    res = curd.create(db, obj_in=obj, creator_id=u['id'])
    if res:
        return respSuccessJson()
    return respErrorJson(error=error_code.ERROR_HIKER_DEVELOPER_ADD_ERROR)


@router.put(api_url + "/{_id}", summary="修改开发者")
async def setRecord(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.user_perm([f"{access_name}:put"])),
                    obj: developer_schemas.DeveloperSchema,
                    _id: int,
                    ):
    data_scope.ensure_writable(curd.get(db, _id=_id), db, u)
    curd.update(db, _id=_id, obj_in=obj, modifier_id=u['id'])
    return respSuccessJson()


@router.delete(api_url + "/{_ids}", summary="删除开发者")
async def delRecord(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.user_perm([f"{access_name}:delete"])),
                    _ids: str,
                    ):
    _ids = list(map(lambda x: int(x), _ids.split(',')))
    _ensure_all_writable(curd, db, _ids, u)
    curd.deletes(db, _ids=_ids, deleter_id=u['id'])
    return respSuccessJson()


@router.put(api_url + "/{_id}/is_manager", summary="修改开发者是否为超管")
async def setIsManager(*,
                       db: Session = Depends(deps.get_db),
                       u: Users = Depends(deps.user_perm([f"{access_name}:put"])),
                       _id: int,
                       obj: developer_schemas.IsManagerSchema
                       ):
    data_scope.ensure_writable(curd.get(db, _id=_id), db, u)
    curd.setIsManager(db, _id=_id, is_manager=obj.is_manager, modifier_id=u['id'])
    return respSuccessJson()


@router.put(api_url + "/{_id}/active", summary="修改开发者是否启用")
async def setActive(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.user_perm([f"{access_name}:put"])),
                    _id: int,
                    obj: ActiveSchema
                    ):
    data_scope.ensure_writable(curd.get(db, _id=_id), db, u)
    curd.setActive(db, _id=_id, active=obj.active, modifier_id=u['id'])
    return respSuccessJson()
