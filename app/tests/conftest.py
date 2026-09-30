#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""curated(亲子精选)单元测试公共装置。

⚠️ 关键: 必须在导入任何 app 模块之前, 把数据库指向独立的临时 SQLite 文件,
   否则测试会连接/污染真实的 app/db/hipy.db(内含用户 Cookie 等生产数据)。
"""
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# ---------------------------------------------------------------- 环境准备
# 注意: 这些 env 必须早于 core.config / db.session 的导入
_TEST_DB_NAME = 'hipy_test_%s' % os.getpid()
_TEST_DB_FILE = os.path.join(APP_DIR, 'db', _TEST_DB_NAME + '.db')

os.environ['SQLALCHEMY_ENGINE'] = 'sqlite'
os.environ['SQL_DATABASE'] = _TEST_DB_NAME
os.environ.setdefault('SQL_USERNAME', 'test')     # sqlite 下无实际用途, 仅为满足必填项
os.environ.setdefault('REDIS_HOST', '127.0.0.1')  # 测试不连 redis
os.environ.setdefault('ECHO_SQL', 'false')
os.environ['SERVER_PROXY'] = ''                   # 测试不联网

import pytest  # noqa: E402

from db.base_class import Base  # noqa: E402
from db.session import engine, SessionLocal  # noqa: E402

# 导入即完成建表 + 增量迁移(_auto_add_columns / _ensure_unique_index)
import apps.curated.models  # noqa: E402,F401
from apps.curated.providers.base import BaseProvider  # noqa: E402

# ---------------------------------------------------------------- 假站点适配器
FAKE_CODE = 'fake'
FAKE_MEDIA = ['B1', 'B2']


class FakeProvider(BaseProvider):
    """不联网的站点适配器, 用于替代 bilibili 进行去重/入库逻辑验证。"""

    code = FAKE_CODE
    name = '测试站点'
    need_login = False

    search_calls = 0
    detail_calls = 0

    def search(self, keyword, page=1, page_size=20):
        type(self).search_calls += 1
        return {'list': [{'media_id': m, 'title': '标题-' + m} for m in FAKE_MEDIA],
                'total': len(FAKE_MEDIA), 'page': page}

    def resolve_url(self, url):
        return {'media_id': 'B1', 'title': '标题-B1'}

    def get_detail(self, media_id):
        type(self).detail_calls += 1
        return {
            'media_id': media_id,
            'title': '详情-' + media_id,
            'cover': 'https://example.com/%s.jpg' % media_id,
            'description': 'desc',
            'duration': 100,
            'up_name': 'up',
            'up_mid': '12345',
            'source_url': 'https://example.com/v/%s' % media_id,
            'play_count': 66,
            'episodes': [
                {'page_index': 1, 'cid': 'cid-%s-1' % media_id, 'title': 'P1', 'duration': 10},
                {'page_index': 2, 'cid': 'cid-%s-2' % media_id, 'title': 'P2', 'duration': 20},
            ],
        }

    def check_viewable(self, media_id):
        return {'ok': True, 'message': '正常'}

    def resolve_play(self, media_id, cid='', qn=80):
        return {'url': 'https://example.com/play/%s.m3u8' % media_id, 'quality': qn}


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope='session', autouse=True)
def _temp_database():
    """整个测试会话使用同一个临时库, 结束后删除文件。"""
    Base.metadata.create_all(engine)
    yield
    engine.dispose()
    for suffix in ('', '-wal', '-shm', '-journal'):
        try:
            os.remove(_TEST_DB_FILE + suffix)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _register_fake_provider(monkeypatch):
    """把假站点注册进注册表, 并重置调用计数。"""
    from apps.curated.providers import registry as _registry
    monkeypatch.setitem(_registry.PROVIDERS, FAKE_CODE, FakeProvider)
    FakeProvider.search_calls = 0
    FakeProvider.detail_calls = 0


@pytest.fixture
def db():
    """干净的 Session(每个用例前清空 curated 相关表)。"""
    from apps.curated.models import (CuratedMedia, CuratedEpisode,
                                     CuratedCategory, CuratedProvider)
    session = SessionLocal()
    for model in (CuratedEpisode, CuratedMedia, CuratedCategory, CuratedProvider):
        session.query(model).delete()
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def curated_db(db):
    """在 db 基础上再插入一条 fake 站点配置行(service 需要)。"""
    from apps.curated.curd import curd_curated_provider
    curd_curated_provider.create(db, obj_in={
        'name': '测试站点', 'code': FAKE_CODE, 'config': '{}',
        'status': 1, 'order_num': 1,
    })
    return db
