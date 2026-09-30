#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库层唯一约束/迁移单元测试。

_ensure_unique_index() 需要满足:
  - 对老库(无唯一约束 + 已有重复行) 能去重并补建唯一索引
  - 去重规则: 活跃优先, 其次保留 id 最小的
  - 幂等: 重复执行不报错、不重复建索引
  - 全新库: 建表时即带 UNIQUE(provider_code, media_id)
"""
import pytest
from sqlalchemy import create_engine, inspect, text

import apps.curated.models as curated_models
from apps.curated.models import CuratedMedia
from apps.curated.models.curated_media import UNIQUE_NAME
from db.session import engine as main_engine

LEGACY_MEDIA_DDL = """
CREATE TABLE curated_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_code VARCHAR(64),
    media_id VARCHAR(64),
    title VARCHAR(128),
    is_deleted INTEGER DEFAULT 0
)
"""

LEGACY_EPISODE_DDL = """
CREATE TABLE curated_episode (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER,
    cid VARCHAR(64),
    is_deleted INTEGER DEFAULT 0
)
"""


def _legacy_engine(tmp_path):
    """构造一个"老版本"的库: 没有唯一约束, 且已有重复数据。"""
    eng = create_engine('sqlite:///' + str(tmp_path / 'legacy.db'))
    with eng.begin() as conn:
        conn.execute(text(LEGACY_MEDIA_DDL))
        conn.execute(text(LEGACY_EPISODE_DDL))
        # B1: id=1 活跃(应保留) / id=2 已软删除(应删除)
        conn.execute(text("INSERT INTO curated_media (id, provider_code, media_id, title, is_deleted)"
                          " VALUES (1, 'fake', 'B1', 'keep', 0)"))
        conn.execute(text("INSERT INTO curated_media (id, provider_code, media_id, title, is_deleted)"
                          " VALUES (2, 'fake', 'B1', 'dup-deleted', 1)"))
        # B2: id=4 活跃 / id=3 活跃(同为活跃时保留 id 最小的 3, 删除 4)
        conn.execute(text("INSERT INTO curated_media (id, provider_code, media_id, title, is_deleted)"
                          " VALUES (3, 'fake', 'B2', 'keep-min', 0)"))
        conn.execute(text("INSERT INTO curated_media (id, provider_code, media_id, title, is_deleted)"
                          " VALUES (4, 'fake', 'B2', 'dup', 0)"))
        # B3: 单条, 不受影响
        conn.execute(text("INSERT INTO curated_media (id, provider_code, media_id, title, is_deleted)"
                          " VALUES (5, 'fake', 'B3', 'only', 0)"))
        # 另一个站点 + 相同 media_id, 属于不同 (provider_code, media_id), 必须保留
        conn.execute(text("INSERT INTO curated_media (id, provider_code, media_id, title, is_deleted)"
                          " VALUES (6, 'other', 'B1', 'other-site', 0)"))
        # 被删行(2/4)的选集, 应一并物理删除
        conn.execute(text("INSERT INTO curated_episode (id, media_id, cid) VALUES (1, 2, 'e1')"))
        conn.execute(text("INSERT INTO curated_episode (id, media_id, cid) VALUES (2, 4, 'e2')"))
        conn.execute(text("INSERT INTO curated_episode (id, media_id, cid) VALUES (3, 1, 'e3')"))
    return eng


def _fetch(eng, sql):
    with eng.connect() as conn:
        return conn.execute(text(sql)).fetchall()


def _unique_index(eng):
    insp = inspect(eng)
    for idx in insp.get_indexes('curated_media'):
        if idx.get('unique') and list(idx.get('column_names') or []) == ['provider_code', 'media_id']:
            return idx
    return None


def test_老库去重并建立唯一索引(tmp_path, monkeypatch):
    eng = _legacy_engine(tmp_path)
    monkeypatch.setattr(curated_models, 'engine', eng)

    curated_models._ensure_unique_index()

    # B1 只剩活跃的 id=1; B2 只剩 id=3; B3 保留; other/B1 属于不同站点必须保留
    assert [tuple(r) for r in _fetch(eng, "SELECT id FROM curated_media WHERE media_id='B1' ORDER BY id")] \
        == [(1,), (6,)]
    assert [tuple(r) for r in _fetch(eng, "SELECT id FROM curated_media WHERE media_id='B2'")] == [(3,)]
    assert [tuple(r) for r in _fetch(eng, "SELECT id FROM curated_media WHERE media_id='B3'")] == [(5,)]
    assert [tuple(r) for r in _fetch(eng, "SELECT title FROM curated_media WHERE id=1")] == [('keep',)]
    assert _unique_index(eng) is not None

    # 被删媒体系的选集已清理, 保留行的选集不受影响
    assert [tuple(r) for r in _fetch(eng, "SELECT id FROM curated_episode ORDER BY id")] == [(3,)]
    eng.dispose()


def test_重复执行保持幂等(tmp_path, monkeypatch):
    eng = _legacy_engine(tmp_path)
    monkeypatch.setattr(curated_models, 'engine', eng)

    curated_models._ensure_unique_index()
    curated_models._ensure_unique_index()   # 第二次不应抛异常

    assert len(_fetch(eng, "SELECT id FROM curated_media")) == 4  # 1/3/5/6
    indexes = [i for i in inspect(eng).get_indexes('curated_media')
               if list(i.get('column_names') or []) == ['provider_code', 'media_id']]
    assert len(indexes) == 1
    eng.dispose()


def test_建立索引后无法再插入重复行(tmp_path, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    eng = _legacy_engine(tmp_path)
    monkeypatch.setattr(curated_models, 'engine', eng)
    curated_models._ensure_unique_index()

    with pytest.raises(IntegrityError):
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO curated_media (provider_code, media_id) VALUES ('fake','B1')"))
    eng.dispose()


def test_全新库建表自带唯一约束():
    """真实模型(__table_args__)必须声明 (provider_code, media_id) 唯一。"""
    constraints = inspect(main_engine).get_unique_constraints('curated_media')
    matched = [uc for uc in constraints
               if list(uc.get('column_names') or []) == ['provider_code', 'media_id']]
    indexes = [i for i in inspect(main_engine).get_indexes('curated_media')
               if i.get('unique') and list(i.get('column_names') or []) == ['provider_code', 'media_id']]
    assert matched or indexes, 'curated_media 缺少 (provider_code, media_id) 唯一约束'


def test_模型导出的约束名与索引一致():
    names = {c.name for c in CuratedMedia.__table__.constraints if c.name}
    assert UNIQUE_NAME in names
