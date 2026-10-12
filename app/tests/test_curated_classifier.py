#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精选内容 - 按标题关键词自动归类单元测试。"""
import pytest

from apps.curated.classifier import classify_title, classify_titles, DEFAULT_CATEGORY


# ------------------------------------------------------------------ 规则命中
@pytest.mark.parametrize('title, expected', [
    ('【全238集】清华大佬终于把英语语法讲明白了', '英语'),
    ('全1000集】必看大语文纪录片《跟着书本去旅行》', '语文'),
    ('全36集 国学经典动画《讲给孩子的三十六计》', '语文'),
    ('1-8季全173集【数字积木】数学英语启蒙必备', '数学'),
    ('央视力荐-专为儿童拍的100部高分纪录片', '儿童科普纪录片'),
    ('【微观小世界】第一季78集全 超萌昆虫趣事儿', '儿童科普纪录片'),
    ('历届奥斯卡最佳动画短片（1932-2022）', '奥斯卡奖&经典动画'),
    # 英语优先: 英语启蒙的「经典动画」不能被动画规则抢走
    ('英语词汇爆涨 全108集【西游记英文版经典动画片】', '英语'),
    # 「双语文稿」不能被当成「语文」
    ('【Easy English】英语口语练习素材合集｜附完整双语文稿', '英语'),
    # 无命中规则时兜底为英语
    ('一个没有任何关键词的标题', DEFAULT_CATEGORY),
])
def test_classify_title(title, expected):
    assert classify_title(title) == expected


def test_classify_titles_等长且顺序一致():
    titles = ['小猪佩奇 中英双字幕', '大语文阅读', 'unmatched']
    assert classify_titles(titles) == ['英语', '语文', DEFAULT_CATEGORY]


# ------------------------------------------------------------------ 自动归类落库
@pytest.fixture
def _seed(curated_db):
    from apps.curated.curd import curd_curated_category, curd_curated_media
    cats = {}
    for name in ('语文', '英语', '数学', '儿童科普纪录片', '艺术', '奥斯卡奖&经典动画'):
        cats[name] = curd_curated_category.create(
            curated_db, obj_in={'name': name, 'status': 1}).id
    curd_curated_media.create(curated_db, obj_in={
        'provider_code': 'fake', 'media_id': 'm1', 'title': '小学英语自然拼读课'})
    curd_curated_media.create(curated_db, obj_in={
        'provider_code': 'fake', 'media_id': 'm2', 'title': '大语文纪录片'})
    curd_curated_media.create(curated_db, obj_in={
        'provider_code': 'fake', 'media_id': 'm3', 'title': '已分类内容',
        'category_id': cats['艺术']})
    return cats


def test_auto_classify_预览不写库(curated_db, _seed):
    from apps.curated.service import curated_service
    res = curated_service.auto_classify(db=curated_db)
    # 只处理 2 条未分类(m1/m2), 不含已分类的 m3
    assert res['total'] == 2
    assert res['updated'] == 0
    assert res['applied'] is False
    plan = {p['category']: p['count'] for p in res['plan']}
    assert plan == {'英语': 1, '语文': 1}


def test_auto_classify_落库且不覆盖已有分类(curated_db, _seed):
    from apps.curated.curd import curd_curated_media
    from apps.curated.service import curated_service
    res = curated_service.auto_classify(db=curated_db, apply=True)
    assert res['updated'] == 2

    m1 = curd_curated_media.getByProviderMediaId(curated_db, 'fake', 'm1')
    m2 = curd_curated_media.getByProviderMediaId(curated_db, 'fake', 'm2')
    m3 = curd_curated_media.getByProviderMediaId(curated_db, 'fake', 'm3')
    assert m1['category_id'] == _seed['英语']
    assert m2['category_id'] == _seed['语文']
    assert m3['category_id'] == _seed['艺术'], '已分类记录不能被覆盖'


def test_auto_classify_按ids限定范围(curated_db, _seed):
    from apps.curated.curd import curd_curated_media
    from apps.curated.service import curated_service
    m1 = curd_curated_media.getByProviderMediaId(curated_db, 'fake', 'm1')
    res = curated_service.auto_classify([m1['id']], db=curated_db, apply=True)
    assert res['updated'] == 1
    assert {p['category']: p['count'] for p in res['plan']} == {'英语': 1}
