#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选集写入逻辑单元测试。

重点验证 1000 集大合集场景下的性能根因修复:
  旧的逐集 create() 会产生 N 次 commit(N 次磁盘 fsync), 现改为 add_all + 单次 commit。
"""
from apps.curated.curd import curd_curated_episode
from apps.curated.service import curated_service
from tests.conftest import FAKE_CODE


def _item(media_id='B1'):
    return {'provider_code': FAKE_CODE, 'media_id': media_id}


class _CommitCounter:
    """统计指定 session 的 commit 次数。"""

    def __init__(self, session):
        self.session = session
        self.count = 0

    def __enter__(self):
        self._orig = self.session.commit
        self.session.commit = self._wrapped
        return self

    def _wrapped(self, *args, **kwargs):
        self.count += 1
        return self._orig(*args, **kwargs)

    def __exit__(self, *exc):
        self.session.commit = self._orig
        return False


def test_替换选集只提交一次(curated_db):
    media = curated_service.import_media(_item('B1'), db=curated_db)

    episodes = [{'page_index': i, 'cid': 'c%d' % i, 'title': 'P%d' % i, 'duration': i}
                for i in range(1, 1001)]
    with _CommitCounter(curated_db) as counter:
        written = curd_curated_episode.replaceByMediaId(curated_db, media['id'], episodes)

    assert written == 1000
    assert counter.count == 1, '选集必须一次性提交, 不允许逐集 commit'
    assert len(curd_curated_episode.getByMediaId(curated_db, media['id'])) == 1000


def test_替换选集是覆盖而不是追加(curated_db):
    media = curated_service.import_media(_item('B1'), db=curated_db)

    curd_curated_episode.replaceByMediaId(
        curated_db, media['id'],
        [{'page_index': 1, 'cid': 'old', 'title': '旧', 'duration': 1}])
    assert len(curd_curated_episode.getByMediaId(curated_db, media['id'])) == 1

    curd_curated_episode.replaceByMediaId(
        curated_db, media['id'],
        [{'page_index': 1, 'cid': 'n1', 'title': '新1', 'duration': 1},
         {'page_index': 2, 'cid': 'n2', 'title': '新2', 'duration': 2}])

    eps = curd_curated_episode.getByMediaId(curated_db, media['id'])
    assert [e['cid'] for e in eps] == ['n1', 'n2']


def test_空选集会清空原有选集(curated_db):
    media = curated_service.import_media(_item('B1'), db=curated_db)
    assert curd_curated_episode.getByMediaId(curated_db, media['id'])

    written = curd_curated_episode.replaceByMediaId(curated_db, media['id'], [])

    assert written == 0
    assert curd_curated_episode.getByMediaId(curated_db, media['id']) == []


def test_选集按order_num排序(curated_db):
    media = curated_service.import_media(_item('B1'), db=curated_db)

    curd_curated_episode.replaceByMediaId(curated_db, media['id'], [
        {'cid': 'c', 'title': 'c', 'order_num': 3},
        {'cid': 'a', 'title': 'a', 'order_num': 1},
        {'cid': 'b', 'title': 'b', 'order_num': 2},
    ])

    eps = curd_curated_episode.getByMediaId(curated_db, media['id'])
    assert [e['cid'] for e in eps] == ['a', 'b', 'c']


def test_多余字段被忽略且缺省值兜底(curated_db):
    media = curated_service.import_media(_item('B1'), db=curated_db)

    curd_curated_episode.replaceByMediaId(curated_db, media['id'], [
        {'不存在的字段': 1},                       # 无 cid/title -> 自动补 P1
    ])

    eps = curd_curated_episode.getByMediaId(curated_db, media['id'])
    assert len(eps) == 1
    assert eps[0]['cid'] == ''
    assert eps[0]['title'] == 'P1'
