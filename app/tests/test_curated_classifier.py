#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精选内容 - 按「分类管理」关键词自动归类单元测试。"""
import pytest

from apps.curated.classifier import (compile_rules, classify_title, classify_titles,
                                     pick_default_name)


def _cats():
    """模拟「分类管理」里的一份配置(order_num 即优先级, is_default 即兜底)。"""
    return [
        {'id': 1, 'name': '语文', 'order_num': 1, 'is_default': 0,
         'keywords': r'(?<!双)语文|大语文|国学|唐诗|三十六计'},
        {'id': 3, 'name': '数学', 'order_num': 2, 'is_default': 0,
         'keywords': r'数学|数字积木'},
        {'id': 4, 'name': '儿童科普纪录片', 'order_num': 4, 'is_default': 0,
         'keywords': r'纪录片|科普|微观小世界'},
        {'id': 2, 'name': '英语', 'order_num': 5, 'is_default': 1,
         'keywords': r'英语|英文|双语|双字幕|English|Phonics'},
        {'id': 6, 'name': '奥斯卡奖&经典动画', 'order_num': 6, 'is_default': 0,
         'keywords': r'奥斯卡|动画短片'},
    ]


# ------------------------------------------------------------------ 规则命中
def test_按关键词命中分类():
    rules = compile_rules(_cats())
    assert classify_title('全1000集大语文纪录片', rules) == '语文'
    assert classify_title('1-8季全173集【数字积木】', rules) == '数学'
    assert classify_title('历届奥斯卡最佳动画短片', rules) == '奥斯卡奖&经典动画'
    assert classify_title('小猪佩奇 中英双字幕', rules) == '英语'
    assert classify_title('一个没有任何关键词的标题', rules) is None


def test_优先级由order_num决定():
    rules = compile_rules(_cats())
    # 同时含「数字积木」(数学) 与「英语」: 数学 order_num 更小, 先命中
    assert classify_title('数字积木英语启蒙', rules) == '数学'
    # 大语文纪录片同时含「语文」与「纪录片」: 语文优先
    assert classify_title('央视力荐大语文纪录片', rules) == '语文'


def test_双语文稿不算语文():
    rules = compile_rules(_cats())
    assert classify_title('英语口语练习素材｜附完整双语文稿', rules) == '英语'


def test_兜底分类优先is_default再回退英语():
    assert pick_default_name(_cats()) == '英语'
    # 没有 is_default 时回退到同名分类「英语」
    cats = [{'id': 1, 'name': '语文', 'order_num': 1, 'keywords': '语文', 'is_default': 0},
            {'id': 2, 'name': '英语', 'order_num': 2, 'keywords': '', 'is_default': 0}]
    assert pick_default_name(cats) == '英语'
    # 指定了别的 is_default 则用它
    cats2 = [{'id': 9, 'name': '其他', 'order_num': 9, 'keywords': '', 'is_default': 1}]
    assert pick_default_name(cats2) == '其他'
    # 既无 is_default 又无「英语」 -> None
    assert pick_default_name([{'id': 1, 'name': '语文', 'order_num': 1, 'keywords': '语文'}]) is None


def test_分类无关键词则不参与匹配_非法正则被忽略():
    cats = [{'id': 1, 'name': '空', 'order_num': 1, 'keywords': '', 'is_default': 0},
            {'id': 2, 'name': '坏正则', 'order_num': 2, 'keywords': '([', 'is_default': 0},
            {'id': 3, 'name': '正常', 'order_num': 3, 'keywords': '语文', 'is_default': 0}]
    rules = compile_rules(cats)
    assert [name for name, _ in rules] == ['正常']
    assert classify_title('大语文', rules) == '正常'


def test_classify_titles_等长且顺序一致():
    rules = compile_rules(_cats())
    assert classify_titles(['小猪佩奇 中英双字幕', '大语文阅读', 'unmatched'], rules) == \
        ['英语', '语文', None]


# ------------------------------------------------------------------ 自动归类落库
@pytest.fixture
def _seed(curated_db):
    from apps.curated.curd import curd_curated_category, curd_curated_media
    cats = {}
    for c in _cats():
        cats[c['name']] = curd_curated_category.create(curated_db, obj_in={
            'name': c['name'], 'status': 1, 'order_num': c['order_num'],
            'keywords': c['keywords'], 'is_default': c['is_default']}).id
    curd_curated_media.create(curated_db, obj_in={
        'provider_code': 'fake', 'media_id': 'm1', 'title': '小学英语自然拼读课'})
    curd_curated_media.create(curated_db, obj_in={
        'provider_code': 'fake', 'media_id': 'm2', 'title': '大语文纪录片'})
    curd_curated_media.create(curated_db, obj_in={
        'provider_code': 'fake', 'media_id': 'm3', 'title': '已分类内容',
        'category_id': cats['奥斯卡奖&经典动画']})
    return cats


def test_auto_classify_预览不写库(curated_db, _seed):
    from apps.curated.service import curated_service
    res = curated_service.auto_classify(db=curated_db)
    # 只处理 2 条未分类(m1/m2), 不含已分类的 m3
    assert res['total'] == 2
    assert res['updated'] == 0
    assert res['applied'] is False
    assert {p['category']: p['count'] for p in res['plan']} == {'英语': 1, '语文': 1}


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
    assert m3['category_id'] == _seed['奥斯卡奖&经典动画'], '已分类记录不能被覆盖'


def test_auto_classify_按ids限定范围(curated_db, _seed):
    from apps.curated.curd import curd_curated_media
    from apps.curated.service import curated_service
    m1 = curd_curated_media.getByProviderMediaId(curated_db, 'fake', 'm1')
    res = curated_service.auto_classify([m1['id']], db=curated_db, apply=True)
    assert res['updated'] == 1
    assert {p['category']: p['count'] for p in res['plan']} == {'英语': 1}


def test_auto_classify_规则随分类管理动态变化(curated_db, _seed):
    """把「英语」关键词清空后, 原本归英语的 m1 应变成兜底(仍是英语);
    再把兜底改到「数学」, 未命中项就归数学 —— 证明规则完全由分类表驱动。"""
    from apps.curated.curd import curd_curated_category, curd_curated_media
    from apps.curated.service import curated_service

    curd_curated_category.update(curated_db, _id=_seed['英语'], obj_in={'keywords': ''})
    curd_curated_media.create(curated_db, obj_in={
        'provider_code': 'fake', 'media_id': 'm4', 'title': '完全无关键词'})
    # 英语仍为兜底: m1(原英语命中) + m4(无命中) 都归英语
    res = curated_service.auto_classify(db=curated_db)
    assert {p['category']: p['count'] for p in res['plan']} == {'英语': 2, '语文': 1}

    # 把兜底改到数学 -> 无命中的 m4 归数学, m1 无规则命中且不再是兜底? m1 仍无规则 -> 兜底数学
    curd_curated_category.update(curated_db, _id=_seed['英语'], obj_in={'is_default': 0})
    curd_curated_category.update(curated_db, _id=_seed['数学'], obj_in={'is_default': 1})
    res = curated_service.auto_classify(db=curated_db)
    plan = {p['category']: p['count'] for p in res['plan']}
    assert plan.get('数学', 0) >= 1
    assert '英语' not in plan
