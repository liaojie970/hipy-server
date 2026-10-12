#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : views.py
# 精选内容 - 后台 API
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from apps.permission.models import Users
from common import deps, error_code, data_scope
from common.resp import respSuccessJson, respErrorJson
from utils.web import getRealHost

from .curd import (curd_curated_provider as curd_provider,
                   curd_curated_category as curd_category,
                   curd_curated_media as curd_media,
                   curd_curated_episode as curd_episode)
from .schemas import (CuratedProviderSchema, ProviderTestSchema,
                      CuratedCategorySchema, CuratedMediaSchema,
                      CuratedMediaBatchSchema, CuratedMediaStatusSchema,
                      CuratedMediaCheckSchema,
                      SearchSchema, ResolveSchema)
from .service import curated_service

router = APIRouter()

access_name = 'curated'
api_url = ''


def _scoped_get(curd, db: Session, _id: int, user) -> dict:
    """按数据范围查单条记录(详情用); 查不到即视为无权限/不存在。"""
    q = db.query(*curd.query_columns).filter(
        curd.model.id == _id, curd.model.is_deleted == 0)
    q = data_scope.apply_scope(q, curd.model, db, user)
    row = q.first()
    return dict(row) if row else {}


def _ensure_all_writable(curd, db: Session, ids, user) -> None:
    """批量预校验: 任一目标不可写则直接抛错(先校验, 后执行, 避免半成功)。"""
    for _id in ids:
        obj = curd.get(db, _id=int(_id))
        data_scope.ensure_writable(obj, db, user)


def _ensure_all_visible(curd, db: Session, ids, user) -> None:
    """批量预校验: 任一目标不可见则直接抛错(只读场景, 如校验可见性)。"""
    for _id in ids:
        obj = curd.get(db, _id=int(_id))
        data_scope.ensure_visible(obj, db, user)


# ======================================================================
# 站点(Provider)
# ======================================================================
@router.get(api_url + '/providers/available', summary="可用的站点类型")
async def availableProviders():
    return respSuccessJson(curated_service.list_providers())


@router.get(api_url + '/providers', summary="站点列表")
async def listProviders(*,
                        db: Session = Depends(deps.get_db),
                        u: Users = Depends(deps.get_current_user),
                        keyword: str = Query(None),
                        status: int = Query(None),
                        page: int = Query(1, gt=0),
                        page_size: int = Query(25, gt=0),
                        ):
    filters = data_scope.apply_scope([], curd_provider.model, db, u)
    if status is not None:
        filters.append(curd_provider.model.status == status)
    if keyword:
        like = f"%{keyword}%"
        filters.append(curd_provider.model.name.ilike(like) | curd_provider.model.code.ilike(like))
    data, total, offset, limit = curd_provider.get_multi(
        db, filters=filters, order_bys=[curd_provider.model.order_num.asc()],
        page=page, page_size=page_size)
    for it in data:
        it['config'] = curated_service.parse_config(it.get('config'))
    return respSuccessJson({'list': data, 'total': total, 'page': page, 'page_size': limit})


@router.get(api_url + '/providers/{_id}', summary="站点详情")
async def getProvider(*,
                      db: Session = Depends(deps.get_db),
                      u: Users = Depends(deps.get_current_user),
                      _id: int):
    data = _scoped_get(curd_provider, db, _id, u)
    if data:
        data['config'] = curated_service.parse_config(data.get('config'))
    return respSuccessJson(data)


@router.post(api_url + '/providers', summary="新增站点")
async def addProvider(*,
                      db: Session = Depends(deps.get_db),
                      u: Users = Depends(deps.user_perm([f"{access_name}:provider:post"])),
                      obj: CuratedProviderSchema,
                      ):
    data = obj.dict(exclude_none=True)
    data['config'] = curated_service.dump_config(data.get('config'))
    res = curd_provider.create(db, obj_in=data, creator_id=u['id'])
    return respSuccessJson({'id': res.id})


@router.put(api_url + '/providers/{_id}', summary="修改站点")
async def setProvider(*,
                      db: Session = Depends(deps.get_db),
                      u: Users = Depends(deps.user_perm([f"{access_name}:provider:put"])),
                      obj: CuratedProviderSchema,
                      _id: int,
                      ):
    data_scope.ensure_writable(curd_provider.get(db, _id=_id), db, u)
    data = obj.dict(exclude_none=True)
    if 'config' in data:
        data['config'] = curated_service.dump_config(data.get('config'))
    curd_provider.update(db, _id=_id, obj_in=data, modifier_id=u['id'])
    return respSuccessJson()


@router.delete(api_url + '/providers/{_id}', summary="删除站点")
async def delProvider(*,
                      db: Session = Depends(deps.get_db),
                      u: Users = Depends(deps.user_perm([f"{access_name}:provider:delete"])),
                      _id: int,
                      ):
    data_scope.ensure_writable(curd_provider.get(db, _id=_id), db, u)
    curd_provider.delete(db, _id=_id, deleter_id=u['id'])
    return respSuccessJson()


@router.post(api_url + '/providers/test', summary="测试站点配置")
async def testProvider(*,
                       db: Session = Depends(deps.get_db),
                       u: Users = Depends(deps.user_perm([f"{access_name}:provider:get"])),
                       obj: ProviderTestSchema,
                       ):
    try:
        res = curated_service.test_config(obj.code, obj.config, db=db)
        return respSuccessJson(res)
    except Exception as e:  # noqa
        return respSuccessJson({'ok': False, 'message': str(e), 'info': {}})


# ======================================================================
# 分类(Category)
# ======================================================================
@router.get(api_url + '/categories', summary="分类列表")
async def listCategories(*,
                         db: Session = Depends(deps.get_db),
                         u: Users = Depends(deps.get_current_user),
                         keyword: str = Query(None),
                         status: int = Query(None),
                         page: int = Query(1, gt=0),
                         page_size: int = Query(100, gt=0),
                         ):
    filters = data_scope.apply_scope([], curd_category.model, db, u)
    if status is not None:
        filters.append(curd_category.model.status == status)
    if keyword:
        filters.append(curd_category.model.name.ilike(f"%{keyword}%"))
    data, total, offset, limit = curd_category.get_multi(
        db, filters=filters, order_bys=[curd_category.model.order_num.asc()],
        page=page, page_size=page_size)
    return respSuccessJson({'list': data, 'total': total, 'page': page, 'page_size': limit})


@router.get(api_url + '/categories/{_id}', summary="分类详情")
async def getCategory(*,
                      db: Session = Depends(deps.get_db),
                      u: Users = Depends(deps.get_current_user),
                      _id: int):
    return respSuccessJson(_scoped_get(curd_category, db, _id, u))


@router.post(api_url + '/categories', summary="新增分类")
async def addCategory(*,
                      db: Session = Depends(deps.get_db),
                      u: Users = Depends(deps.user_perm([f"{access_name}:category:post"])),
                      obj: CuratedCategorySchema,
                      ):
    data = obj.dict(exclude_none=True)
    if not data.get('order_num'):
        data['order_num'] = curd_category.getMaxOrderNum(db) + 1
    res = curd_category.create(db, obj_in=data, creator_id=u['id'])
    return respSuccessJson({'id': res.id})


@router.put(api_url + '/categories/{_id}', summary="修改分类")
async def setCategory(*,
                      db: Session = Depends(deps.get_db),
                      u: Users = Depends(deps.user_perm([f"{access_name}:category:put"])),
                      obj: CuratedCategorySchema,
                      _id: int,
                      ):
    data_scope.ensure_writable(curd_category.get(db, _id=_id), db, u)
    curd_category.update(db, _id=_id, obj_in=obj.dict(exclude_none=True), modifier_id=u['id'])
    return respSuccessJson()


@router.delete(api_url + '/categories/{_id}', summary="删除分类")
async def delCategory(*,
                      db: Session = Depends(deps.get_db),
                      u: Users = Depends(deps.user_perm([f"{access_name}:category:delete"])),
                      _id: int,
                      ):
    data_scope.ensure_writable(curd_category.get(db, _id=_id), db, u)
    curd_category.delete(db, _id=_id, deleter_id=u['id'])
    return respSuccessJson()


# ======================================================================
# 媒体(Media)
# ======================================================================
@router.get(api_url + '/media', summary="媒体列表")
async def listMedia(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.get_current_user),
                    provider_code: str = Query(None),
                    category_id: int = Query(None),
                    status: int = Query(None),
                    visible: int = Query(None),
                    keyword: str = Query(None),
                    page: int = Query(1, gt=0),
                    page_size: int = Query(25, gt=0),
                    ):
    scope_filters = data_scope.apply_scope([], curd_media.model, db, u)
    data, total, offset, limit = curd_media.queryList(
        db, provider_code=provider_code, category_id=category_id, status=status,
        visible=visible, keyword=keyword, extra_filters=scope_filters,
        page=page, page_size=page_size)
    return respSuccessJson({'list': data, 'total': total, 'page': page, 'page_size': limit})


@router.get(api_url + '/media/{_id}', summary="媒体详情")
async def getMedia(*,
                   db: Session = Depends(deps.get_db),
                   u: Users = Depends(deps.get_current_user),
                   _id: int):
    data = _scoped_get(curd_media, db, _id, u)
    if data:
        data['episodes'] = curd_episode.getByMediaId(db, _id)
    return respSuccessJson(data)


@router.post(api_url + '/media/batch', summary="批量入库")
async def batchMedia(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.user_perm([f"{access_name}:media:post"])),
                    obj: CuratedMediaBatchSchema,
                    ):
    res = curated_service.batch_import(
        obj.provider_code, obj.items, category_id=obj.category_id,
        status=obj.status, visible=obj.visible, creator_id=u['id'],
        skip_existing=getattr(obj, 'skip_existing', True),
        refresh=getattr(obj, 'refresh', False),
        db=db)
    return respSuccessJson(res)


@router.put(api_url + '/media/{_id}', summary="修改媒体")
async def setMedia(*,
                   db: Session = Depends(deps.get_db),
                   u: Users = Depends(deps.user_perm([f"{access_name}:media:put"])),
                   obj: CuratedMediaSchema,
                   _id: int,
                   ):
    data_scope.ensure_writable(curd_media.get(db, _id=_id), db, u)
    curd_media.update(db, _id=_id, obj_in=obj.dict(exclude_none=True), modifier_id=u['id'])
    return respSuccessJson()


@router.delete(api_url + '/media/{_id}', summary="删除媒体")
async def delMedia(*,
                   db: Session = Depends(deps.get_db),
                   u: Users = Depends(deps.user_perm([f"{access_name}:media:delete"])),
                   _id: int,
                   ):
    data_scope.ensure_writable(curd_media.get(db, _id=_id), db, u)
    curd_episode.deleteByMediaId(db, _id)
    curd_media.delete(db, _id=_id, deleter_id=u['id'])
    return respSuccessJson()


@router.put(api_url + '/media/status/batch', summary="批量设置审核状态")
async def batchMediaStatus(*,
                          db: Session = Depends(deps.get_db),
                          u: Users = Depends(deps.user_perm([f"{access_name}:media:put"])),
                          obj: CuratedMediaStatusSchema,
                          ):
    _ensure_all_writable(curd_media, db, obj.ids, u)
    for _id in obj.ids:
        curd_media.setStatus(db, _id=int(_id), status=obj.status, modifier_id=u['id'])
    return respSuccessJson()


@router.post(api_url + '/media/visible/batch', summary="批量设置是否可见")
async def batchMediaVisible(*,
                           db: Session = Depends(deps.get_db),
                           u: Users = Depends(deps.user_perm([f"{access_name}:media:put"])),
                           obj: CuratedMediaStatusSchema,
                           ):
    _ensure_all_writable(curd_media, db, obj.ids, u)
    for _id in obj.ids:
        curd_media.update(db, _id=int(_id), obj_in={'visible': obj.status}, modifier_id=u['id'])
    return respSuccessJson()


@router.post(api_url + '/media/remove/batch', summary="批量删除媒体")
async def batchRemoveMedia(*,
                          db: Session = Depends(deps.get_db),
                          u: Users = Depends(deps.user_perm([f"{access_name}:media:delete"])),
                          obj: CuratedMediaStatusSchema,
                          ):
    _ensure_all_writable(curd_media, db, obj.ids, u)
    for _id in obj.ids:
        curd_episode.deleteByMediaId(db, int(_id))
    curd_media.deletes(db, _ids=[int(i) for i in obj.ids], deleter_id=u['id'])
    return respSuccessJson()


@router.post(api_url + '/media/check/batch', summary="批量校验可见性与可播放")
async def batchCheckMedia(*,
                        db: Session = Depends(deps.get_db),
                        u: Users = Depends(deps.user_perm([f"{access_name}:media:get"])),
                        obj: CuratedMediaCheckSchema,
                        ):
    _ensure_all_visible(curd_media, db, obj.ids, u)
    res = curated_service.check_batch([int(i) for i in obj.ids], db=db)
    return respSuccessJson(res)


# ======================================================================
# 搜索 / 解析 / 播放
# ======================================================================
@router.post(api_url + '/search', summary="搜索站点内容")
async def searchMedia(*,
                     db: Session = Depends(deps.get_db),
                     u: Users = Depends(deps.user_perm([f"{access_name}:media:get"])),
                     obj: SearchSchema,
                     ):
    try:
        res = curated_service.search(obj.provider_code, obj.keyword, page=obj.page,
                                     page_size=obj.page_size, db=db)
        return respSuccessJson(res)
    except Exception as e:  # noqa
        return respErrorJson(error=error_code.ERROR_CURATED_SEARCH_ERROR, msg=str(e))


@router.post(api_url + '/resolve', summary="解析粘贴链接")
async def resolveUrl(*,
                    db: Session = Depends(deps.get_db),
                    u: Users = Depends(deps.user_perm([f"{access_name}:media:get"])),
                    obj: ResolveSchema,
                    ):
    try:
        return respSuccessJson(curated_service.resolve(obj.provider_code, obj.url, db=db))
    except Exception as e:  # noqa
        return respErrorJson(error=error_code.ERROR_CURATED_RESOLVE_ERROR, msg=str(e))


@router.get(api_url + '/play', summary="解析播放直链")
async def resolvePlay(*,
                     db: Session = Depends(deps.get_db),
                     provider_code: str = Query(...),
                     media_id: str = Query(...),
                     cid: str = Query(''),
                     qn: int = Query(80),
                     ):
    try:
        return respSuccessJson(curated_service.resolve_play(provider_code, media_id, cid, qn=qn, db=db))
    except Exception as e:  # noqa
        return respErrorJson(error=error_code.ERROR_CURATED_PLAY_ERROR, msg=str(e))


@router.get(api_url + '/catalog', summary="精选库快照(调试用)")
async def catalog(*, db: Session = Depends(deps.get_db)):
    categories = curated_service.get_categories(db)
    media = curated_service.get_media_list(db=db)
    return respSuccessJson({'categories': categories, 'media': media})


@router.get(api_url + '/kid_config', summary="生成儿童专用配置地址")
async def kidConfig(*,
                   db: Session = Depends(deps.get_db),
                   u: Users = Depends(deps.user_perm([f"{access_name}:media:get"])),
                   request: Request,
                   mode: int = Query(0, description="配置模式 0:t4 1:t3"),
                   ensure: bool = Query(True, description="是否自动创建订阅"),
                   ):
    """
    返回一个只包含【亲子精选】源的订阅配置地址, 便于直接给孩子的设备使用。
    会确保存在一条 reg=亲子精选、mode=0 的启用订阅。
    """
    result = {'mode': mode, 'created': False, 'name': '亲子精选'}
    if ensure:
        try:
            sub = curated_service.ensure_kid_subscription(db=db)
        except Exception as e:  # noqa
            return respErrorJson(error=error_code.ERROR_INTERNAL.set_msg(f'创建订阅失败:{e}'))
        result.update({
            'created': sub.get('created', False),
            'name': sub.get('name') or '亲子精选',
            'reg': sub.get('reg'),
            'sub_code': sub.get('code') or '',
        })
    else:
        result['sub_code'] = 'qinzi01'
    host = str(request.base_url).rstrip('/')
    host = getRealHost(host, request)
    sub_code = result.get('sub_code') or ''
    result['config_url'] = f'{host}/config/{mode}?sub={sub_code}'
    result['tvbox_url'] = f'clan://{host}/config/{mode}?sub={sub_code}'
    result['tips'] = '把 config_url 填到孩子设备的TVBox配置地址即可, 该配置只包含【亲子精选】一个源'
    return respSuccessJson(result)
