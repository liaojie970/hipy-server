#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : bilibili.py
# 精选内容 - 哔哩哔哩站点适配器
"""
B站适配器。

配置项(config 字典, 存于 t_curated_provider.config):
    cookie : 登录后的完整 Cookie 字符串(至少包含 SESSDATA), 用于搜索/播放鉴权
    ua     : 可选, 自定义 User-Agent
    qn     : 可选, 默认清晰度(默认 80 => 1080P, 无登录态时 B站会自动降级)
    proxy  : 可选, 代理设置。空=遵循系统/环境代理; none=强制直连; 也可写 127.0.0.1:7897

说明:
- 若本机无法直连 B站(如处于需代理的网络), 在站点配置里填写 proxy, 或保证系统代理可用。
- 搜索/playurl 接口需要 wbi 签名, 这里已实现。
"""
import hashlib
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import requests

from .base import BaseProvider

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# wbi 签名混淆表
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")


def _get_mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def _duration_to_seconds(text: Any) -> int:
    """将 '12:34' / '1:02:03' / 数字(秒) 统一转换为一秒数"""
    if isinstance(text, (int, float)):
        return int(text)
    text = str(text or "").strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


class BilibiliProvider(BaseProvider):
    code = "bilibili"
    name = "哔哩哔哩"
    need_login = True

    API = "https://api.bilibili.com"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.session = requests.Session()
        self.session_proxy = self.setup_session_proxy(self.session)
        self.session.headers.update({
            "User-Agent": self.config.get("ua") or DEFAULT_UA,
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
        })
        cookie = (self.config.get("cookie") or "").strip()
        if cookie:
            self.session.headers["Cookie"] = cookie
        self._wbi_keys: Optional[tuple] = None
        self._wbi_ts: float = 0

    # ------------------------------------------------------------------
    # 底层请求
    # ------------------------------------------------------------------
    def _wbi_sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        img_key, sub_key = self._get_wbi_keys()
        mixin_key = _get_mixin_key(img_key + sub_key)
        params = dict(params)
        params["wts"] = int(time.time())
        params = dict(sorted(params.items()))
        params = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in params.items()}
        query = urllib.parse.urlencode(params)
        params["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
        return params

    def _get_wbi_keys(self) -> tuple:
        if self._wbi_keys and time.time() - self._wbi_ts < 1800:
            return self._wbi_keys
        # nav 接口即使未登录也会返回 wbi_img
        data = self._raw_get("/x/web-interface/nav")
        wbi = (data.get("data") or {}).get("wbi_img") or {}
        img_url = wbi.get("img_url") or ""
        sub_url = wbi.get("sub_url") or ""
        img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
        self._wbi_keys = (img_key, sub_key)
        self._wbi_ts = time.time()
        return self._wbi_keys

    def _raw_get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> dict:
        try:
            r = self.session.get(self.API + path, params=params or {}, timeout=timeout)
            return r.json()
        except Exception as e:  # noqa
            return {"code": -1, "message": f"请求失败: {e}"}

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None, wbi: bool = False,
             timeout: int = 15) -> dict:
        params = dict(params or {})
        if wbi:
            params = self._wbi_sign(params)
        return self._raw_get(path, params=params, timeout=timeout)

    # ------------------------------------------------------------------
    # 规范化
    # ------------------------------------------------------------------
    def _normalize_search_item(self, it: dict) -> Dict[str, Any]:
        bvid = it.get("bvid") or ""
        pic = it.get("pic") or ""
        if pic.startswith("//"):
            pic = "https:" + pic
        return {
            "provider_code": self.code,
            "media_id": bvid,
            "title": _strip_html(it.get("title") or ""),
            "cover": pic,
            "description": _strip_html(it.get("description") or ""),
            "duration": _duration_to_seconds(it.get("duration")),
            "up_name": it.get("author") or "",
            "up_mid": str(it.get("mid") or ""),
            "source_url": f"https://www.bilibili.com/video/{bvid}",
            "play_count": it.get("play") or "",
            "extra": {"aid": it.get("aid"), "type": "video"},
        }

    def _normalize_video_detail(self, d: dict) -> Dict[str, Any]:
        bvid = d.get("bvid") or ""
        owner = d.get("owner") or {}
        stat = d.get("stat") or {}
        pages = d.get("pages") or []
        episodes: List[Dict[str, Any]] = []
        for idx, p in enumerate(pages):
            episodes.append({
                "page_index": idx,
                "cid": str(p.get("cid") or ""),
                "title": p.get("part") or f"P{idx + 1}",
                "duration": int(p.get("duration") or 0),
                "order_num": idx,
            })
        if not episodes and d.get("cid"):
            episodes.append({
                "page_index": 0,
                "cid": str(d.get("cid")),
                "title": d.get("title") or "正片",
                "duration": int(d.get("duration") or 0),
                "order_num": 0,
            })
        return {
            "provider_code": self.code,
            "media_id": bvid,
            "title": d.get("title") or "",
            "cover": d.get("pic") or "",
            "description": d.get("desc") or "",
            "duration": int(d.get("duration") or 0),
            "up_name": owner.get("name") or "",
            "up_mid": str(owner.get("mid") or ""),
            "source_url": f"https://www.bilibili.com/video/{bvid}",
            "play_count": stat.get("view") or 0,
            "extra": {"aid": d.get("aid"), "videos": d.get("videos"), "type": "video"},
            "episodes": episodes,
        }

    # ------------------------------------------------------------------
    # 接口实现
    # ------------------------------------------------------------------
    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        params = {
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "page_size": min(max(page_size, 1), 50),
        }
        data = self._get("/x/web-interface/wbi/search/type", params, wbi=True)
        if data.get("code") != 0:
            # 退化为老接口
            data = self._get("/x/web-interface/search/type", params)
        if data.get("code") != 0:
            raise ValueError(data.get("message") or "搜索失败")
        result = data.get("data") or {}
        items = result.get("result") or []
        total = result.get("numResults")
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = len(items)
        return {
            "list": [self._normalize_search_item(it) for it in items if it.get("bvid")],
            "total": total or len(items),
            "page": page,
        }

    def resolve_url(self, url: str) -> Dict[str, Any]:
        text = (url or "").strip()
        m = _BV_RE.search(text)
        if not m:
            # 允许直接输入 av 号
            av = re.search(r"av(\d+)", text, re.I)
            if av:
                data = self._get("/x/web-interface/view", {"aid": av.group(1)})
                if data.get("code") == 0:
                    return self._normalize_video_detail(data["data"])
            raise ValueError("无法解析该链接, 请粘贴B站视频链接或 BV 号")
        return self.get_video(m.group(1))

    def get_video(self, bvid: str) -> Dict[str, Any]:
        data = self._get("/x/web-interface/view", {"bvid": bvid})
        if data.get("code") != 0:
            raise ValueError(data.get("message") or "获取视频信息失败")
        return self._normalize_video_detail(data["data"])

    def get_detail(self, media_id: str) -> Dict[str, Any]:
        return self.get_video(media_id)

    def check_viewable(self, media_id: str) -> Dict[str, Any]:
        data = self._get("/x/web-interface/view", {"bvid": media_id})
        if data.get("code") == 0:
            return {"ok": True, "message": "ok", "info": self._normalize_video_detail(data["data"])}
        return {"ok": False, "message": data.get("message") or "不可见", "info": {}}

    def resolve_play(self, media_id: str, cid: str = "", qn: int = 80) -> Dict[str, Any]:
        if not cid:
            detail = self.get_video(media_id)
            eps = detail.get("episodes") or []
            if not eps:
                raise ValueError("该视频没有可播放的选集")
            cid = eps[0]["cid"]
        qn = int(self.config.get("qn") or qn or 80)
        params = {
            "bvid": media_id,
            "cid": cid,
            "qn": qn,
            "fnver": 0,
            "fnval": 1,   # 1 = MP4(durl), 兼容性最好
            "fourk": 1,
        }
        data = self._get("/x/player/wbi/playurl", params, wbi=True)
        if data.get("code") != 0:
            data = self._get("/x/player/playurl", params)
        if data.get("code") != 0:
            raise ValueError(data.get("message") or "获取播放地址失败")
        d = data.get("data") or {}
        durl = d.get("durl") or []
        url = ""
        if durl:
            best = max(durl, key=lambda x: x.get("size") or 0)
            url = best.get("url") or ""
        if not url:
            dash = d.get("dash") or {}
            videos = dash.get("video") or []
            if videos:
                best_v = max(videos, key=lambda x: x.get("bandwidth") or 0)
                url = best_v.get("baseUrl") or best_v.get("base_url") or ""
        if not url:
            raise ValueError("未获取到可用播放地址(可能是会员/地区限制)")
        headers = {
            "Referer": "https://www.bilibili.com/",
            "User-Agent": self.session.headers.get("User-Agent", DEFAULT_UA),
        }
        return {"url": url, "headers": headers, "quality": d.get("quality")}

    def test(self) -> Dict[str, Any]:
        data = self._get("/x/web-interface/nav")
        d = data.get("data") or {}
        code = data.get("code")
        # -101 = 账号未登录: 网络正常, 只是没有有效登录态, 不算配置错误
        if code not in (0, -101):
            return {"ok": False, "message": data.get("message") or "配置无效", "info": {}}
        is_login = bool(d.get("isLogin"))
        info = {
            "is_login": is_login,
            "uname": d.get("uname") or "",
            "mid": d.get("mid") or "",
            "vip": (d.get("vipStatus") == 1),
        }
        if self.config.get("cookie") and not is_login:
            return {"ok": False, "message": "Cookie 已失效或格式不正确", "info": info}
        return {"ok": True, "message": "登录态正常" if is_login else "未配置 Cookie(仅能播放低清晰度)", "info": info}
