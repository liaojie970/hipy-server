#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : base.py
# 精选内容 - 站点适配器基类
"""
所有内容站点(Provider)都需要实现本基类。
新增站点时, 继承 BaseProvider 并在 registry 中注册即可。
"""
import socket
from typing import Any, Dict, List, Optional


class BaseProvider:
    # 站点唯一编码, 例如 bilibili / youtube
    code: str = ""
    # 站点展示名称
    name: str = ""
    # 是否需要登录态(cookie)
    need_login: bool = False

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    # ------------------------------------------------------------------
    # 公共工具
    # ------------------------------------------------------------------
    def setup_session_proxy(self, session) -> str:
        """根据 config['proxy'] 为 requests.Session 配置代理。

        - 未配置(空): 遵循系统/环境代理(requests 默认行为) —— 浏览器能用一般就行
        - none/direct/off/0: 强制直连, 忽略系统代理
        - 其他: 作为代理地址(可省略 http://), 如 127.0.0.1:7897
        :return: 生效描述, 便于日志
        """
        proxy = str(self.config.get('proxy') or '').strip()
        if proxy:
            if proxy.lower() in ('none', 'direct', 'no', 'off', '0', 'false'):
                session.trust_env = False
                session.proxies = {}
                return 'direct'
            if '://' not in proxy:
                proxy = 'http://' + proxy
            # 代理指向本机回环但端口无人监听(常见于把 A 机器的配置同步到了 B 机器),
            # 此时请求必然被本机代理拒绝, 自动回退直连, 避免播放解析莫名失败。
            if self._is_dead_loopback_proxy(proxy):
                session.trust_env = False
                session.proxies = {}
                return 'direct(loopback proxy unreachable, fallback)'
            session.trust_env = False
            session.proxies = {'http': proxy, 'https': proxy}
            return proxy
        # 未配置: 遵循系统/环境代理
        session.trust_env = True
        return 'system'

    @staticmethod
    def _is_dead_loopback_proxy(proxy: str) -> bool:
        """判断代理是否为「本机回环地址且端口未监听」"""
        try:
            from urllib.parse import urlparse
            u = urlparse(proxy)
            host = (u.hostname or '').lower()
            port = u.port
            if host not in ('127.0.0.1', 'localhost', '::1', '0.0.0.0') or not port:
                return False
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(('127.0.0.1', port)) != 0
        except Exception:  # noqa
            return False

    # ------------------------------------------------------------------
    # 以下方法由子类实现
    # ------------------------------------------------------------------
    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """
        关键词搜索
        :return {'list': [media_item, ...], 'total': int, 'page': int}
        """
        raise NotImplementedError

    def resolve_url(self, url: str) -> Dict[str, Any]:
        """
        解析粘贴的视频链接/ID, 返回单个 media_item
        :raise ValueError 解析失败
        """
        raise NotImplementedError

    def get_detail(self, media_id: str) -> Dict[str, Any]:
        """
        根据站点内媒体ID获取详情(含 episodes 选集)
        :raise ValueError 获取失败
        """
        raise NotImplementedError

    def check_viewable(self, media_id: str) -> Dict[str, Any]:
        """
        校验当前登录账号是否可见该视频
        :return {'ok': bool, 'message': str}
        """
        raise NotImplementedError

    def resolve_play(self, media_id: str, cid: str = "", qn: int = 80) -> Dict[str, Any]:
        """
        解析播放直链
        :return {'url': str, 'headers': dict, 'quality': int}
        """
        raise NotImplementedError

    def test(self) -> Dict[str, Any]:
        """
        测试站点配置是否可用(登录态等)
        :return {'ok': bool, 'message': str, 'info': dict}
        """
        return {"ok": True, "message": "ok", "info": {}}
