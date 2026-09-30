#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「亲子精选」三层去重 / 入库逻辑单元测试。

覆盖:
  ① 应用层 upsert  : 命中则更新, 未命中则新增
  ② 软删除复活     : 删除后重新入库复用同一行(id 不变)
  ③ 数据库层硬约束 : UNIQUE(provider_code, media_id) 阻止重复行
  ④ 并发兜底       : 插入撞唯一约束时回滚并改走更新
  ⑤ 批量入库       : skip_existing / refresh / 复活 / 错误条目
"""
import pytest
from sqlalchemy.exc import IntegrityError

from apps.curated.curd import curd_curated_media, curd_curated_episode
from apps.curated.models.curated_media import CuratedMedia
from apps.curated.service import curated_service
from tests.conftest import FAKE_CODE, FakeProvider


def _item(media_id='B1', **extra):
    data = {'provider_code': FAKE_CODE, 'media_id': media_id}
    data.update(extra)
    return data


def _count(db):
    return db.query(CuratedMedia).count()


# --------------------------------------------------------------------- ① 新增 / 更新
def test_首次入库新增一行并写入选集(curated_db):
    res = curated_service.import_media(_item('B1'), db=curated_db)

    assert res['is_new'] is True
    assert _count(curated_db) == 1

    row = curd_curated_media.getByProviderMediaId(curated_db, FAKE_CODE, 'B1')
    assert row['title'] == '详情-B1'            # 详情被拉取并落库
    assert row['up_mid'] == '12345'
    assert row['play_count'] == 66
    eps = curd_curated_episode.getByMediaId(curated_db, res['id'])
    assert len(eps) == 2
    assert [e['cid'] for e in eps] == ['cid-B1-1', 'cid-B1-2']


def test_重复入库更新而非新增(curated_db):
    first = curated_service.import_media(_item('B1'), db=curated_db)
    second = curated_service.import_media(_item('B1'), db=curated_db)

    assert first['is_new'] is True
    assert second['is_new'] is False
    assert second['id'] == first['id']
    assert _count(curated_db) == 1


def test_重复入库不会让选集翻倍(curated_db):
    first = curated_service.import_media(_item('B1'), db=curated_db)
    curated_service.import_media(_item('B1'), db=curated_db)

    eps = curd_curated_episode.getByMediaId(curated_db, first['id'])
    assert len(eps) == 2          # 替换而非追加


# --------------------------------------------------------------------- ② 软删除复活
def test_软删除后重新入库复活同一行(curated_db):
    first = curated_service.import_media(_item('B1'), db=curated_db)

    assert curd_curated_media.delete(curated_db, _id=first['id']) == 1
    assert curd_curated_media.getByProviderMediaId(curated_db, FAKE_CODE, 'B1') == {}
    soft = curd_curated_media.getByProviderMediaId(
        curated_db, FAKE_CODE, 'B1', include_deleted=True)
    assert soft['is_deleted'] == 1

    again = curated_service.import_media(_item('B1'), db=curated_db)

    assert again['id'] == first['id']          # 复用同一行
    assert again['is_new'] is False
    assert _count(curated_db) == 1             # 没有产生第二行
    row = curd_curated_media.getByProviderMediaId(curated_db, FAKE_CODE, 'B1')
    assert row['is_deleted'] == 0              # 已复活


def test_不同媒体id互不影响(curated_db):
    a = curated_service.import_media(_item('B1'), db=curated_db)
    b = curated_service.import_media(_item('B2'), db=curated_db)

    assert a['id'] != b['id']
    assert _count(curated_db) == 2


# --------------------------------------------------------------------- ③ 数据库硬约束
def test_唯一约束阻止重复插入(db):
    curd_curated_media.create(db, obj_in={'provider_code': FAKE_CODE, 'media_id': 'B1'})

    with pytest.raises(IntegrityError):
        curd_curated_media.create(db, obj_in={'provider_code': FAKE_CODE, 'media_id': 'B1'})
    db.rollback()
    assert _count(db) == 1


def test_唯一约束对软删除行同样生效(db):
    """即使旧行已软删除, 也不允许再插一条相同 (provider_code, media_id)。"""
    curd_curated_media.create(db, obj_in={'provider_code': FAKE_CODE, 'media_id': 'B1'})
    row = curd_curated_media.getByProviderMediaId(db, FAKE_CODE, 'B1')
    curd_curated_media.delete(db, _id=row['id'])

    with pytest.raises(IntegrityError):
        curd_curated_media.create(db, obj_in={'provider_code': FAKE_CODE, 'media_id': 'B1'})
    db.rollback()
    assert _count(db) == 1


# --------------------------------------------------------------------- ④ 并发兜底
def test_并发撞唯一约束时回滚并改走更新(curated_db, monkeypatch):
    created = curd_curated_media.create(
        curated_db, obj_in={'provider_code': FAKE_CODE, 'media_id': 'B1', 'title': '旧'})
    curated_db.commit()
    real = curd_curated_media.getByProviderMediaId
    state = {'n': 0}

    def flaky(db_, code, media_id, include_deleted=False):
        state['n'] += 1
        if state['n'] == 1:
            return {}          # 假装查不到 -> 走 insert -> 触发 UNIQUE 冲突
        return real(db_, code, media_id, include_deleted=include_deleted)

    monkeypatch.setattr(curd_curated_media, 'getByProviderMediaId', flaky)

    _id, is_new = curd_curated_media.upsertByProviderMediaId(
        curated_db, FAKE_CODE, 'B1', {'title': '新'})

    assert is_new is False
    assert _id == created.id
    assert _count(curated_db) == 1
    assert curd_curated_media.getByProviderMediaId(curated_db, FAKE_CODE, 'B1')['title'] == '新'


# --------------------------------------------------------------------- ⑤ 批量入库
def test_批量入库_首次全部新增(curated_db):
    res = curated_service.batch_import(
        FAKE_CODE, [{'media_id': 'B1'}, {'media_id': 'B2'}], db=curated_db)

    assert res['created'] == 2 and res['updated'] == 0
    assert res['skipped_count'] == 0 and res['failed'] == 0
    assert _count(curated_db) == 2


def test_批量入库_重复点击幂等秒回(curated_db):
    curated_service.batch_import(FAKE_CODE, [{'media_id': 'B1'}, {'media_id': 'B2'}],
                                 db=curated_db)
    FakeProvider.detail_calls = 0

    res = curated_service.batch_import(FAKE_CODE, [{'media_id': 'B1'}, {'media_id': 'B2'}],
                                       db=curated_db)

    assert res['created'] == 0 and res['updated'] == 0
    assert res['skipped_count'] == 2
    assert len(res['skipped']) == 2 and all(s['skipped'] for s in res['skipped'])
    assert _count(curated_db) == 2
    assert FakeProvider.detail_calls == 0      # 已存在 -> 不再联网补详情


def test_批量入库_复活已软删除的行(curated_db):
    first = curated_service.batch_import(FAKE_CODE, [{'media_id': 'B1'}], db=curated_db)
    local_id = first['success'][0]['id']
    curd_curated_media.delete(curated_db, _id=local_id)

    res = curated_service.batch_import(FAKE_CODE, [{'media_id': 'B1'}], db=curated_db)

    assert res['updated'] == 1 and res['skipped_count'] == 0
    assert res['success'][0]['id'] == local_id
    assert _count(curated_db) == 1
    assert curd_curated_media.getByProviderMediaId(curated_db, FAKE_CODE, 'B1')['is_deleted'] == 0


def test_批量入库_skip_existing为False时强制刷新(curated_db):
    curated_service.batch_import(FAKE_CODE, [{'media_id': 'B1'}], db=curated_db)
    FakeProvider.detail_calls = 0

    res = curated_service.batch_import(FAKE_CODE, [{'media_id': 'B1'}],
                                       skip_existing=False, db=curated_db)

    assert res['updated'] == 1
    assert FakeProvider.detail_calls == 1      # 强制重新拉详情
    assert _count(curated_db) == 1


def test_批量入库_已存在且refresh为False时不联网(curated_db):
    curated_service.batch_import(FAKE_CODE, [{'media_id': 'B1'}], db=curated_db)
    FakeProvider.detail_calls = 0

    res = curated_service.batch_import(FAKE_CODE, [{'media_id': 'B1'}],
                                       skip_existing=False, refresh=False, db=curated_db)

    assert res['updated'] == 1
    assert FakeProvider.detail_calls == 0


def test_批量入库_缺少媒体id计入失败(curated_db):
    res = curated_service.batch_import(FAKE_CODE, [{'title': '没有id'}], db=curated_db)

    assert res['failed'] == 1 and res['created'] == 0
    assert res['errors'][0]['error'] == '缺少 media_id'
    assert _count(curated_db) == 0


def test_批量入库_自带选集时不再联网(curated_db):
    item = {'media_id': 'B1',
            'episodes': [{'page_index': 1, 'cid': 'x', 'title': '自带', 'duration': 1}]}
    FakeProvider.detail_calls = 0

    res = curated_service.batch_import(FAKE_CODE, [item], db=curated_db)

    assert res['created'] == 1
    assert FakeProvider.detail_calls == 0
    eps = curd_curated_episode.getByMediaId(curated_db, res['success'][0]['id'])
    assert [e['cid'] for e in eps] == ['x']


# --------------------------------------------------------------------- 搜索标注
def test_搜索标注是否已入库(curated_db):
    curated_service.import_media(_item('B1'), db=curated_db)

    res = curated_service.search(FAKE_CODE, '任意关键词', db=curated_db)

    flags = {it['media_id']: (it['imported'], it['local_id']) for it in res['list']}
    assert flags['B1'][0] is True and flags['B1'][1] is not None
    assert flags['B2'][0] is False and flags['B2'][1] is None


# --------------------------------------------------------------------- 运行时读取
def test_运行时只返回已通过且可见的媒体(curated_db):
    """status=1/visible=1 才出现在 TVBox 源里。"""
    item = curated_service.import_media(_item('B1'), db=curated_db)
    curated_service.import_media(_item('B2', ), db=curated_db)
    curd_curated_media.update(curated_db, _id=item['id'], obj_in={'status': 0})

    visible = curated_service.get_media_list(db=curated_db)

    assert [m['media_id'] for m in visible] == ['B2']
    assert visible[0]['episodes'], '运行时数据需带上选集'
