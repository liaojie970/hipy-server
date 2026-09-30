#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精选内容 - 无副作用工具函数单元测试(config 解析、代理设置、注册表)。"""
import pytest

from apps.curated.providers import registry
from apps.curated.providers.base import BaseProvider
from apps.curated.service import CuratedService, _is_active, curated_service


# ------------------------------------------------------------------ config 解析
@pytest.mark.parametrize('raw, expected', [
    (None, {}),
    ('', {}),
    ('{}', {}),
    ('{"cookie": "SESSDATA=abc"}', {'cookie': 'SESSDATA=abc'}),
    ({'cookie': 'x'}, {'cookie': 'x'}),
    ('not-json', {}),          # 脏数据不能抛异常
    ('[1,2,3]', {}),           # 合法 JSON 但不是对象
    ('"str"', {}),
])
def test_parse_config(raw, expected):
    assert CuratedService.parse_config(raw) == expected


@pytest.mark.parametrize('raw, expected', [
    (None, ''),
    ('', '{}'),               # 空串不是合法 JSON -> 降级为 {}
    ('not-json', '{}'),        # 脏数据降级为 {}    ('{"a": 1}', '{"a": 1}'),  # 已是 JSON 字符串则原样保留
    ({'a': 1, 'b': None}, '{"a": 1, "b": null}'),
])
def test_dump_config(raw, expected):
    assert CuratedService.dump_config(raw) == expected


def test_parse_dump_往返一致():
    cfg = {'cookie': 'SESSDATA=x', 'proxy': '127.0.0.1:7897', 'qn': 80}
    assert CuratedService.parse_config(CuratedService.dump_config(cfg)) == cfg


# ------------------------------------------------------------------ _is_active
@pytest.mark.parametrize('row, expected', [
    (None, False),        # 无记录
    ({}, False),          # 空 dict 视为无记录
    ({'is_deleted': 0}, True),
    ({'is_deleted': 1}, False),
    ({'is_deleted': None}, True),   # 历史数据可能为 NULL
    ({'is_deleted': '0'}, True),
])
def test_is_active(row, expected):
    assert _is_active(row) is expected


# ------------------------------------------------------------------ 站点代理配置
class _FakeSession:
    def __init__(self):
        self.trust_env = None
        self.proxies = None


@pytest.mark.parametrize('proxy, expect_desc', [
    ('', 'system'),
    ('   ', 'system'),
    (None, 'system'),
    ('none', 'direct'),
    ('DIRECT', 'direct'),
    ('off', 'direct'),
    ('0', 'direct'),
    ('127.0.0.1:7897', 'http://127.0.0.1:7897'),           # 自动补 http://
    ('http://127.0.0.1:7897', 'http://127.0.0.1:7897'),
    ('socks5://127.0.0.1:1080', 'socks5://127.0.0.1:1080'),
])
def test_setup_session_proxy(proxy, expect_desc):
    session = _FakeSession()
    provider = BaseProvider({'proxy': proxy})

    desc = provider.setup_session_proxy(session)

    assert desc == expect_desc
    if expect_desc == 'system':
        assert session.trust_env is True
        assert session.proxies is None
    elif expect_desc == 'direct':
        assert session.trust_env is False
        assert session.proxies == {}
    else:
        assert session.trust_env is False
        assert session.proxies == {'http': expect_desc, 'https': expect_desc}


def test_嵌入死代理的环境变量不会污染已配置代理(monkeypatch):
    """IDE 注入 HTTP_PROXY 时, 站点显式配置的 proxy 必须优先(本项目真实踩过的坑)。"""
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:17890')
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:17890')
    session = _FakeSession()

    desc = BaseProvider({'proxy': '127.0.0.1:7897'}).setup_session_proxy(session)

    assert desc == 'http://127.0.0.1:7897'
    assert session.trust_env is False, '必须关闭环境变量代理继承'


# ------------------------------------------------------------------ 注册表
def test_list_providers_包含哔哩哔哩():
    codes = {p['code'] for p in registry.list_providers()}
    assert 'bilibili' in codes


def test_get_provider_未知编码返回None():
    assert registry.get_provider('not-exist') is None


def test_get_provider_返回实例并带上配置():
    provider = registry.get_provider('bilibili', {'proxy': 'none'})
    assert provider is not None
    assert provider.code == 'bilibili'
    assert provider.config == {'proxy': 'none'}


def test_service_list_providers_聚合已注册站点():
    data = curated_service.list_providers()
    assert any(p['code'] == 'bilibili' for p in data)


def test_get_provider_instance_未配置站点报错(curated_db):
    with pytest.raises(ValueError):
        curated_service.get_provider_instance(curated_db, 'bilibili')


def test_get_provider_instance_已配置站点可用(curated_db):
    from apps.curated.curd import curd_curated_provider
    curd_curated_provider.create(curated_db, obj_in={
        'name': 'B站', 'code': 'bilibili', 'config': '{"cookie":"x"}', 'status': 1})

    provider = curated_service.get_provider_instance(curated_db, 'bilibili')

    assert provider.code == 'bilibili'
    assert provider.config.get('cookie') == 'x'


def test_get_provider_config_未配置时返回空字典(curated_db):
    assert curated_service.get_provider_config(curated_db, 'bilibili') == {}
