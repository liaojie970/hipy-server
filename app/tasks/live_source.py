#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直播源聚合任务

把多个 IPTV 直播源（fanmingming/live、Tvlist-awesome-m3u-m3u8 等）下载下来，
统一解析成 m3u，按频道名去重、跨源补台标、可选并发测活，最后输出一份本地 m3u。

用法：
    # 由后台「定时任务」调度（推荐）
    func_name = tasks.live_source.main

    # 或命令行手动执行（在 app/ 目录下）
    python -m tasks.live_source

配置文件：t4/files/json/live_sources.json
输出文件：t4/files/m3u/live_merged.m3u
         t4/files/json/live_merged_meta.json（统计信息）
         可选：t4/files/txt/mytv.txt（开启 output.mirror_local_txt 时，兼容旧配置）
"""

import hashlib
import json
import os
import random
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    from core.logger import logger
except Exception:  # 允许脱离 hipy 环境单独调试
    import logging

    logger = logging.getLogger(__name__)

from utils.define import DEFAULT_USER_AGENT
from utils.live_epg import norm_epg_key

APP_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = APP_DIR / 't4' / 'files'
CONFIG_PATH = FILES_DIR / 'json' / 'live_sources.json'

_URL_RE = re.compile(r'^(?:https?|rtmp|rtmps|rtsp|rtp|rtp2|udp|proxy)://', re.I)
_EXTINF_RE = re.compile(r'^#EXTINF:\s*(-?\d+(?:\.\d+)?)\s*(.*)$', re.I)
_ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
_GENRE_RE = re.compile(r'^(.+?)\s*,\s*#genre#\s*$', re.I)
# iptv-org 的 tvg-id 形如 CCTV1.cn@SD，去掉国家/清晰度后缀后才能跨源匹配
_TVG_COUNTRY_RE = re.compile(r'\.[a-z]{2}(?:@[a-z0-9]+)?$', re.I)

# 归一化频道名时需要忽略的常见后缀/修饰词（只用于匹配，不影响最终显示名）
_NOISE_WORDS = [
    '高清', '超清', '标清', '蓝光', '4k', '8k', 'uhd', 'hd', 'sd', '50帧', '60帧',
    '频道', '直播', '备用', '测试',
    # CCTV 频道的描述性后缀
    '综合', '财经', '综艺', '中文国际', '国际', '体育赛事', '体育', '电影',
    '电视剧', '纪录片', '纪录', '科教', '戏曲', '社会与法', '新闻', '少儿',
    '音乐', '军事', '农业', '欧洲', '美洲', '赛事',
]
_NOISE_RE = re.compile('|'.join(re.escape(w) for w in sorted(_NOISE_WORDS, key=len, reverse=True)), re.I)


# --------------------------------------------------------------------------- #
# 配置 / 网络
# --------------------------------------------------------------------------- #
def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f'直播源配置文件不存在: {path}')
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _build_session(user_agent: str, trust_env: bool) -> requests.Session:
    s = requests.Session()
    s.trust_env = trust_env
    s.headers.update({
        'User-Agent': user_agent or DEFAULT_USER_AGENT,
        'Accept': '*/*',
    })
    return s


def _url_variants(url: str, req_cfg: dict) -> list:
    """GitHub raw 地址优先走加速前缀，失败再回退直连。

    支持两种写法（可同时存在）：
    - github_proxy: "https://gh-proxy.com/"          单个前缀
    - github_proxies: ["https://gh-proxy.com/", ...] 多个前缀，按顺序尝试
    """
    variants = []
    proxies = []
    single = str(req_cfg.get('github_proxy') or '').strip()
    if single:
        proxies.append(single)
    multi = req_cfg.get('github_proxies') or []
    if isinstance(multi, str):
        multi = [multi]
    if isinstance(multi, list):
        proxies.extend(str(p).strip() for p in multi if str(p or '').strip())

    seen = set()
    for proxy in proxies:
        proxy = proxy.rstrip('/') + '/'
        if proxy in seen:
            continue
        seen.add(proxy)
        if 'raw.githubusercontent.com' in url and not url.startswith(proxy):
            variants.append(proxy + url)
    variants.append(url)
    return variants


def _timeout(req_cfg: dict, override: float = None):
    connect = float(req_cfg.get('connect_timeout') or 5)
    read = float(override or req_cfg.get('timeout') or 15)
    # 连接超时必须短：GitHub Pages 会同时解析出 IPv6/IPv4，黑洞地址会把标量 timeout 拖满
    return (min(connect, read), read)


def _env_proxy_configured() -> bool:
    keys = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')
    return any(os.environ.get(k) for k in keys)


def fetch_bytes(url: str, req_cfg: dict, timeout: float = None, fallback_urls: list = None) -> bytes:
    timeout = _timeout(req_cfg, timeout)
    retries = max(1, int(req_cfg.get('retries') or 1))
    direct_fallback = bool(req_cfg.get('direct_fallback', True))
    ua = req_cfg.get('user_agent') or DEFAULT_USER_AGENT
    candidates = [url] + [u for u in (fallback_urls or []) if u and u != url]
    last_err = None
    # 先用系统代理环境，失败后再强制直连（避免坏代理把任务卡死）
    # 没有配置代理时不要重复跑两遍，否则每个地址白等一轮超时
    if direct_fallback and _env_proxy_configured():
        trust_env_options = [True, False]
    else:
        trust_env_options = [False]
    for attempt in range(retries):
        for raw_url in candidates:
            for target in _url_variants(raw_url, req_cfg):
                for trust_env in trust_env_options:
                    session = _build_session(ua, trust_env)
                    try:
                        r = session.get(target, timeout=timeout, allow_redirects=True)
                        r.raise_for_status()
                        return r.content
                    except Exception as e:  # noqa
                        last_err = e
                        if req_cfg.get('quiet'):
                            logger.debug(f'[live_source] 下载失败({target}, trust_env={trust_env}): {e}')
                        else:
                            logger.info(f'[live_source] 下载失败({target}, trust_env={trust_env}): {e}')
                    finally:
                        session.close()
        if attempt + 1 < retries:
            time.sleep(1 + attempt)
    raise RuntimeError(f'下载失败: {url} -> {last_err}')


def fetch_text(url: str, req_cfg: dict, timeout: float = None, fallback_urls: list = None) -> str:
    return _decode(fetch_bytes(url, req_cfg, timeout=timeout, fallback_urls=fallback_urls))


def _decode(content: bytes) -> str:
    for enc in ('utf-8-sig', 'utf-8', 'gb18030'):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode('latin-1', errors='replace')


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _split_display(text: str) -> str:
    """取 #EXTINF 最后一个引号外的逗号之后的显示名。"""
    in_quote = False
    last_comma = -1
    for i, ch in enumerate(text):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ',' and not in_quote:
            last_comma = i
    return text[last_comma + 1:].strip() if last_comma >= 0 else ''


def map_group(raw: str, group_map: dict) -> str:
    """分组映射。iptv-org 会出现 `Animation;Kids` 这种多值分组，取第一个能映射的。"""
    raw = (raw or '').strip()
    if not raw:
        return '其他'
    if raw in group_map:
        return group_map[raw]
    for part in re.split(r'[;,]', raw):
        part = part.strip()
        if part and part in group_map:
            return group_map[part]
    return raw


def _make_channel(attrs: dict, display: str, url: str, source: dict, order: int, group_map: dict) -> dict:
    name = (display or attrs.get('tvg-name') or '').strip()
    group = map_group(attrs.get('group-title') or source.get('default_group'), group_map)
    return {
        'name': name or '未命名频道',
        'tvg_id': (attrs.get('tvg-id') or '').strip(),
        'tvg_name': (attrs.get('tvg-name') or '').strip(),
        'logo': (attrs.get('tvg-logo') or '').strip(),
        'group': group or '其他',
        'url': url.strip(),
        'source': source.get('name') or '',
        'priority': int(source.get('priority') or 100),
        'order': order,
    }


def parse_m3u(text: str, source: dict, start_order: int = 0, group_map: dict = None) -> list:
    group_map = group_map or {}
    channels = []
    pending = None
    order = start_order
    for raw in text.splitlines():
        line = raw.strip().lstrip('\ufeff')
        if not line:
            continue
        if line.upper().startswith('#EXTINF'):
            m = _EXTINF_RE.match(line)
            attrs = dict(_ATTR_RE.findall(line))
            display = _split_display(m.group(2)) if m else ''
            pending = (attrs, display)
            continue
        if line.upper().startswith('#EXTGRP:') and pending:
            pending[0]['group-title'] = line.split(':', 1)[1].strip()
            continue
        if line.startswith('#'):
            continue
        if not pending:
            continue
        if not _URL_RE.match(line):
            pending = None
            continue
        attrs, display = pending
        channels.append(_make_channel(attrs, display, line, source, order, group_map))
        order += 1
        pending = None
    return channels


def parse_txt(text: str, source: dict, start_order: int = 0, group_map: dict = None) -> list:
    """兼容 TVBox 常用的 `分组,#genre#` + `频道名,url` 文本格式。"""
    group_map = group_map or {}
    channels = []
    current_group = source.get('default_group') or '其他'
    order = start_order
    for raw in text.splitlines():
        line = raw.strip().lstrip('\ufeff')
        if not line or line.startswith('#'):
            continue
        m = _GENRE_RE.match(line)
        if m:
            current_group = m.group(1).strip()
            continue
        if ',' not in line:
            continue
        name, url = line.split(',', 1)
        name, url = name.strip(), url.strip()
        if not name or not _URL_RE.match(url):
            continue
        group = map_group(current_group, group_map)
        channels.append({
            'name': name,
            'tvg_id': '',
            'tvg_name': name,
            'logo': '',
            'group': group or '其他',
            'url': url,
            'source': source.get('name') or '',
            'priority': int(source.get('priority') or 100),
            'order': order,
        })
        order += 1
    return channels


def parse_source(text: str, source: dict, start_order: int = 0, group_map: dict = None) -> list:
    fmt = str(source.get('format') or 'auto').lower()
    if fmt == 'txt':
        return parse_txt(text, source, start_order, group_map)
    if fmt == 'm3u':
        return parse_m3u(text, source, start_order, group_map)
    head = text[:2048]
    if '#EXTM3U' in head.upper() or '#EXTINF' in head.upper():
        return parse_m3u(text, source, start_order, group_map)
    return parse_txt(text, source, start_order, group_map)


# --------------------------------------------------------------------------- #
# 去重 / 台标 / 测活
# --------------------------------------------------------------------------- #
def norm_key(name: str) -> str:
    s = unicodedata.normalize('NFKC', name or '').lower()
    s = re.sub(r'[\s\-_·•|/\\]+', '', s)
    s = re.sub(r'[（）()\[\]【】《》<>]+', '', s)
    s = _NOISE_RE.sub('', s)
    return s


def norm_tvg_id(tvg_id: str) -> str:
    """把 `CCTV1.cn@SD` / `CCTV1.us@HD` 归一成 `cctv1`。

    fanmingming 用 `CCTV1`，iptv-org 用 `CCTV1.cn@SD`；不归一化就无法跨源去重、补台标。
    """
    s = unicodedata.normalize('NFKC', tvg_id or '').strip().lower()
    s = _TVG_COUNTRY_RE.sub('', s)
    s = re.sub(r'@.*$', '', s)
    return re.sub(r'[\s\-_·•|/\\]+', '', s)


def _dedupe(channels: list, cfg: dict) -> list:
    max_per_name = max(1, int(cfg.get('max_per_name') or 1))
    dedupe_url = bool(cfg.get('dedupe_url', True))

    channels.sort(key=lambda c: (c['priority'], c['order']))
    seen_url = set()
    name_count = {}
    result = []
    for c in channels:
        url = c['url']
        if dedupe_url and url in seen_url:
            continue
        key = norm_tvg_id(c['tvg_id']) or norm_key(c['name']) or c['name'].lower()
        if name_count.get(key, 0) >= max_per_name:
            continue
        name_count[key] = name_count.get(key, 0) + 1
        seen_url.add(url)
        result.append(c)
    return result


def _backfill_logos(channels: list) -> int:
    """用已带台标的频道（通常是 fanmingming）给 Tvlist 等无台标条目补 logo。"""
    logo_by_key = {}
    for c in channels:
        if not c.get('logo'):
            continue
        tid = norm_tvg_id(c.get('tvg_id'))
        if tid:
            logo_by_key.setdefault(tid, c['logo'])
        key = norm_key(c['name'])
        if key:
            logo_by_key.setdefault(key, c['logo'])

    filled = 0
    for c in channels:
        if c.get('logo'):
            continue
        logo = ''
        tid = norm_tvg_id(c.get('tvg_id'))
        if tid:
            logo = logo_by_key.get(tid, '')
        if not logo:
            logo = logo_by_key.get(norm_key(c['name']), '')
        if logo:
            c['logo'] = logo
            filled += 1
    return filled


def _rewrite_logo_url(url: str, logo_cfg: dict) -> str:
    """按配置把已知会超时的台标域名改写为可用镜像（如 fanmingming 的 GitHub raw）。"""
    for rule in logo_cfg.get('url_rewrites') or []:
        if not isinstance(rule, dict):
            continue
        src = str(rule.get('from') or '')
        dst = str(rule.get('to') or '')
        if src and dst and url.startswith(src):
            return dst + url[len(src):]
    return url


def _logo_filename(url: str) -> str:
    path = urlparse(url).path
    base = path.rsplit('/', 1)[-1] or 'logo.png'
    base = re.sub(r'[^A-Za-z0-9._-]+', '_', base).strip('._') or 'logo'
    ext = Path(base).suffix.lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp'):
        ext = '.png'
    stem = Path(base).stem[:40] or 'logo'
    digest = hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]
    return f'{stem}-{digest}{ext}'


def _looks_like_image(data: bytes) -> bool:
    if not data:
        return False
    head = data[:512].lstrip().lower()
    return (
        data.startswith(b'\x89PNG') or data.startswith(b'\xff\xd8') or
        data.startswith(b'GIF8') or data.startswith(b'RIFF') or
        data.startswith(b'BM') or b'<svg' in head
    )


def _cache_logos(channels: list, cfg: dict, req_cfg: dict) -> dict:
    """把频道台标下载到本地，并把 m3u 里的 tvg-logo 改写成本地地址。

    下载失败时保留原始 URL，不影响直播源本身。
    """
    logo_cfg = cfg.get('logo') or {}
    if not logo_cfg.get('cache_local'):
        return {}

    rel_dir = str(logo_cfg.get('dir') or 'm3u/logo').strip('/')
    out_dir = FILES_DIR / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    timeout = float(logo_cfg.get('timeout') or 8)
    workers = max(1, int(logo_cfg.get('workers') or 8))
    max_bytes = int(logo_cfg.get('max_bytes') or 2 * 1024 * 1024)
    cache_existing = bool(logo_cfg.get('cache_existing', True))
    public_base = str(logo_cfg.get('public_base_url') or '{{host}}').rstrip('/')
    # 台标失败很常见（imgur 等被墙），不要按直播源的重试次数反复等
    logo_req = dict(req_cfg)
    logo_req['retries'] = max(1, int(logo_cfg.get('retry') or 1))
    logo_req['direct_fallback'] = False
    logo_req['quiet'] = True

    urls = []
    seen = set()
    for c in channels:
        url = (c.get('logo') or '').strip()
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    stats = {'total': len(urls), 'downloaded': 0, 'reused': 0, 'failed': 0, 'rewritten': 0}
    if not urls:
        return stats

    def one(url: str):
        filename = _logo_filename(url)
        path = out_dir / filename
        if cache_existing and path.exists() and path.stat().st_size > 0:
            return url, filename, 'reused', None
        target = _rewrite_logo_url(url, logo_cfg)
        try:
            data = fetch_bytes(target, logo_req, timeout=timeout)
            if len(data) > max_bytes:
                raise RuntimeError(f'文件过大 {len(data)} > {max_bytes}')
            if not _looks_like_image(data):
                raise RuntimeError('返回内容不是图片')
            tmp = path.with_name(path.name + '.tmp')
            tmp.write_bytes(data)
            os.replace(tmp, path)
            return url, filename, 'downloaded', None
        except Exception as e:  # noqa
            return url, filename, 'failed', str(e)

    url_map = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, u): u for u in urls}
        for i, future in enumerate(as_completed(futures), 1):
            url, filename, status, err = future.result()
            if status in ('downloaded', 'reused'):
                url_map[url] = f'{public_base}/files/{rel_dir}/{filename}'
                stats[status] += 1
                stats['rewritten'] += 1
            else:
                stats['failed'] += 1
                logger.debug(f'[live_source] 台标缓存失败 {url}: {err}')
            if i % 50 == 0:
                logger.info(f'[live_source] 台标缓存进度 {i}/{len(urls)}')

    if logo_cfg.get('rewrite_m3u', True):
        for c in channels:
            local = url_map.get((c.get('logo') or '').strip())
            if local:
                c['logo'] = local

    logger.info(
        f'[live_source] 台标缓存完成：共 {stats["total"]} 个，'
        f'下载 {stats["downloaded"]}，复用 {stats["reused"]}，失败 {stats["failed"]}'
    )
    return stats


# 测活实现已迁移到 tasks/live_health.py（三级测活 + 台账 + 软删除），
# 这里保留两个薄封装，兼容旧代码/旧配置里的直接调用。
def _check_one(channel: dict, check_cfg: dict) -> bool:
    """返回 True=保留。非 http(s) 协议无法用 requests 测活，按配置决定是否保留。"""
    from tasks import live_health
    return bool(live_health.probe(channel['url'], {'check': check_cfg})['ok'])


def _check_channels(channels: list, check_cfg: dict) -> tuple:
    from tasks import live_health
    kept, dropped, _stats = live_health.check_channels(channels, {'check': check_cfg})
    return kept, dropped


def _dedupe_urls(channels: list) -> list:
    """只按 URL 去重，不做频道取舍。放在测活前，纯粹为了少发请求。"""
    seen, result = set(), []
    for c in channels:
        url = c.get('url')
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(c)
    return result


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def _merge_previous_ok(channels: list, out_cfg: dict, cfg: dict, live_health) -> list:
    """把上一份 m3u 里“台账没说死”的线路并回来。

    上游快照抖动（同一批源几十分钟内换掉大部分 IP）时，一次聚合可能把可用清单砍掉一大半。
    回补的线路会在下一轮 live_check（≤ 6h）里复验：真死的自然被剔掉，不用靠人扫。
    已判 dead 的线路绝不回补，避免又把死线塞回去。
    """
    m3u_path = FILES_DIR / (out_cfg.get('m3u') or 'm3u/live_merged.m3u')
    if not m3u_path.exists():
        return channels
    prev = live_health.parse_m3u_channels(m3u_path.read_text(encoding='utf-8'))
    if not prev:
        return channels
    entries = (live_health.load_ledger(cfg) or {}).get('entries') or {}
    have = {ch['url'] for ch in channels}
    base_order = max([int(c.get('order') or 0) for c in channels] or [0]) + 1
    merged = []
    for ch in prev:
        url = ch.get('url') or ''
        if not url or url in have:
            continue
        entry = entries.get(live_health.url_key(url, cfg)) or {}
        if entry.get('state') == 'dead':
            continue
        name = ch.get('name') or '未命名频道'
        merged.append({
            'name': name,
            'tvg_id': '',
            'tvg_name': name,
            'logo': '',
            'group': ch.get('group') or '其他',
            'url': url,
            'source': 'prev-m3u',
            'priority': 900,          # 排在本轮新测活的线路后面，当备线
            'order': base_order + len(merged),
        })
        have.add(url)
    if not merged:
        return channels
    logger.warning(f'[live_source] 本轮结果 {len(channels)} 条，上一份 {len(prev)} 条：'
                   f'回补未被判死的 {len(merged)} 条，交给下一轮 live_check 复验')
    return channels + merged


def _render_m3u(channels: list, epg: str) -> str:
    lines = ['#EXTM3U']
    if epg:
        lines[0] = f'#EXTM3U x-tvg-url="{epg}"'
    for c in channels:
        attrs = []
        if c.get('tvg_id'):
            attrs.append(f'tvg-id="{c["tvg_id"]}"')
        display = c.get('name') or c.get('tvg_name') or ''
        tvg_name = c.get('tvg_name') or display
        if tvg_name:
            attrs.append(f'tvg-name="{tvg_name}"')
        if c.get('logo'):
            attrs.append(f'tvg-logo="{c["logo"]}"')
        attrs.append(f'group-title="{c.get("group") or "其他"}"')
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{display}')
        lines.append(c['url'])
    return '\n'.join(lines) + '\n'


def _write_atomic(path: Path, content: str, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        try:
            path.with_name(path.name + '.bak').write_bytes(path.read_bytes())
        except Exception:  # noqa
            pass
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    os.replace(tmp, path)


def _xmltv_dt(value: str):
    m = re.match(r'^(\d{14})', value or '')
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), '%Y%m%d%H%M%S')
    except ValueError:
        return None


def _epg_public_url(epg_cfg: dict, rel_path: str) -> str:
    base = str(epg_cfg.get('public_base_url') or '{{host}}').rstrip('/')
    return f'{base}/files/{rel_path.strip("/")}'


def _cache_epg(channels: list, cfg: dict, req_cfg: dict) -> tuple:
    """缓存并裁剪 XMLTV EPG，同时生成给 /epg 接口使用的频道索引。

    说明：TVBoxOS 会把 lives.epg 当成“按频道查询”的地址；如果直接给它整份 XML，
    它会为每个频道重复下载整份 XML。因此这里额外生成 json/epg_index.json，
    由 /epg?ch=xxx&date=xxx 只返回该频道当天的节目。
    """
    epg_cfg = cfg.get('epg_cache') or {}
    external = str(cfg.get('epg') or '')
    if not epg_cfg.get('enabled'):
        return external, {'enabled': False}

    url = str(epg_cfg.get('url') or external)
    fallbacks = epg_cfg.get('fallback_urls') or []
    xml_rel = str(epg_cfg.get('xml_file') or 'txt/e.xml').strip('/')
    index_rel = str(epg_cfg.get('index_file') or 'json/epg_index.json').strip('/')
    xml_path = FILES_DIR / xml_rel
    index_path = FILES_DIR / index_rel
    write_xml = bool(epg_cfg.get('write_xml', True))
    epg_url = _epg_public_url(epg_cfg, xml_rel) if write_xml else external
    stats = {
        'enabled': True, 'url': url, 'downloaded': False, 'reused': False,
        'channels': 0, 'programs': 0, 'error': None,
    }

    def _fill_stats_from_index():
        """复用缓存时把统计信息补全，避免 meta 里显示 0 频道。"""
        try:
            old = json.loads(index_path.read_text(encoding='utf-8'))
            stats['channels'] = int(old.get('channel_count') or 0)
            stats['programs'] = int(old.get('program_count') or 0)
            stats['updated_at'] = old.get('updated_at')
        except Exception:  # noqa
            pass

    max_age = float(epg_cfg.get('max_age_hours') or 0)
    if max_age > 0 and index_path.exists() and (not write_xml or xml_path.exists()):
        age = time.time() - index_path.stat().st_mtime
        if age < max_age * 3600:
            stats['reused'] = True
            _fill_stats_from_index()
            logger.info(f'[live_source] EPG 缓存未过期（{age / 3600:.1f}h），跳过下载')
            return epg_url, stats

    try:
        text = fetch_text(url, req_cfg, timeout=epg_cfg.get('timeout') or 60,
                          fallback_urls=fallbacks)
        root = ET.fromstring(text)
    except Exception as e:  # noqa
        stats['error'] = str(e)
        logger.warning(f'[live_source] EPG 下载/解析失败，保留旧缓存: {e}')
        if index_path.exists():
            stats['reused'] = True
            _fill_stats_from_index()
            return epg_url, stats
        return external, stats

    now = datetime.now()
    keep_days = int(epg_cfg.get('keep_days') or 0)
    if keep_days > 0:
        min_dt = now - timedelta(days=1)
        max_dt = now + timedelta(days=keep_days)
    else:
        min_dt = None
        max_dt = None

    channel_meta = {}
    programs_by_id = {}
    for elem in root:
        if elem.tag == 'channel':
            cid = (elem.get('id') or '').strip()
            if not cid:
                continue
            names = [(d.text or '').strip() for d in elem.findall('display-name') if (d.text or '').strip()]
            channel_meta[cid] = names
        elif elem.tag == 'programme':
            cid = (elem.get('channel') or '').strip()
            if not cid:
                continue
            start = _xmltv_dt(elem.get('start'))
            stop = _xmltv_dt(elem.get('stop'))
            if not start or not stop:
                continue
            if max_dt and start > max_dt:
                continue
            if min_dt and stop < min_dt:
                continue
            title = (elem.findtext('title') or '').strip()
            if not title:
                continue
            programs_by_id.setdefault(cid, []).append({
                'title': title,
                'start': start.strftime('%Y-%m-%d %H:%M:%S'),
                'end': stop.strftime('%Y-%m-%d %H:%M:%S'),
            })

    for progs in programs_by_id.values():
        progs.sort(key=lambda p: p['start'])

    if epg_cfg.get('trim_to_channels', True):
        used_keys = set()
        used_ids = set()
        for c in channels:
            for value in (c.get('name'), c.get('tvg_name'), c.get('tvg_id')):
                key = norm_epg_key(value)
                if key:
                    used_keys.add(key)
            tid = norm_tvg_id(c.get('tvg_id'))
            if tid:
                used_ids.add(tid)
        keep_ids = set()
        for cid, names in channel_meta.items():
            candidates = {norm_epg_key(cid)}
            candidates.update(norm_epg_key(n) for n in names)
            if cid.lower() in used_ids or norm_tvg_id(cid) in used_ids or candidates & used_keys:
                keep_ids.add(cid)
        if not keep_ids:
            logger.warning('[live_source] EPG 频道与当前列表未匹配，回退保留全部频道')
            keep_ids = set(channel_meta)
    else:
        keep_ids = set(channel_meta)

    channels_out = {}
    for cid in keep_ids:
        progs = programs_by_id.get(cid) or []
        if progs:
            channels_out[cid] = progs

    if not channels_out:
        stats['error'] = 'EPG 中没有可用节目'
        logger.warning('[live_source] EPG 解析后没有节目，保留旧缓存')
        if index_path.exists():
            stats['reused'] = True
            _fill_stats_from_index()
            return epg_url, stats
        return external, stats

    # 频道名/tvg-id -> EPG 频道 id，供 /epg 接口按频道查询
    keys = {}
    for cid in channels_out:
        keys.setdefault(norm_epg_key(cid), cid)
        for name in channel_meta.get(cid, []):
            keys.setdefault(norm_epg_key(name), cid)

    id_lookup = {norm_tvg_id(cid): cid for cid in channels_out}
    for c in channels:
        tid = norm_tvg_id(c.get('tvg_id'))
        target = id_lookup.get(tid)
        if not target:
            target = keys.get(norm_epg_key(c.get('name')))
        if target:
            for value in (c.get('name'), c.get('tvg_name')):
                key = norm_epg_key(value)
                if key:
                    keys.setdefault(key, target)

    index = {
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'source': url,
        'upstream_api': epg_cfg.get('upstream_api') or 'https://epg.mxdyeah.top/api/diyp/?ch={name}&date={date}',
        'keep_days': keep_days,
        'channel_count': len(channels_out),
        'program_count': sum(len(p) for p in channels_out.values()),
        'keys': keys,
        'channels': channels_out,
    }
    _write_atomic(index_path, json.dumps(index, ensure_ascii=False, separators=(',', ':')))
    logger.info(
        f'[live_source] EPG 索引已写入 {index_path}：'
        f'{index["channel_count"]} 个频道 / {index["program_count"]} 条节目'
    )

    if write_xml:
        tv = ET.Element('tv', attrib=dict(root.attrib))
        for elem in root:
            if elem.tag == 'channel' and elem.get('id') in channels_out:
                tv.append(elem)
            elif elem.tag == 'programme' and elem.get('channel') in channels_out:
                start = _xmltv_dt(elem.get('start'))
                stop = _xmltv_dt(elem.get('stop'))
                if not start or not stop:
                    continue
                if max_dt and start > max_dt:
                    continue
                if min_dt and stop < min_dt:
                    continue
                tv.append(elem)
        xml_bytes = ET.tostring(tv, encoding='utf-8', xml_declaration=True)
        _write_atomic(xml_path, xml_bytes.decode('utf-8'))
        logger.info(f'[live_source] EPG XML 已写入 {xml_path}')

    stats.update({
        'downloaded': True,
        'channels': index['channel_count'],
        'programs': index['program_count'],
    })
    return epg_url, stats


def _group_channels(channels: list, group_order: list) -> list:
    if not group_order:
        return channels
    rank = {g: i for i, g in enumerate(group_order)}
    # 保持组内原有顺序；未知分组排在最后
    return sorted(
        channels,
        key=lambda c: (rank.get(c.get('group'), len(rank)), c['priority'], c['order']),
    )


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run(config_path: Path = CONFIG_PATH) -> dict:
    cfg = load_config(config_path)
    req_cfg = cfg.get('request') or {}
    group_map = cfg.get('group_map') or {}
    sources = cfg.get('sources') or []

    all_channels = []
    source_stats = []
    errors = []

    for source in sources:
        if not source.get('enabled'):
            continue
        name = source.get('name') or source.get('url')
        try:
            t0 = time.time()
            logger.info(f'[live_source] 拉取 {name}: {source.get("url")}')
            text = fetch_text(source['url'], req_cfg, timeout=source.get('timeout'),
                              fallback_urls=source.get('fallback_urls'))
            part = parse_source(text, source, len(all_channels), group_map)
            all_channels.extend(part)
            source_stats.append({'name': name, 'count': len(part), 'error': None})
            logger.info(f'[live_source] {name} 解析到 {len(part)} 条，耗时 {time.time() - t0:.1f}s')
        except Exception as e:  # noqa
            errors.append(f'{name}: {e}')
            source_stats.append({'name': name, 'count': 0, 'error': str(e)})
            logger.warning(f'[live_source] {name} 拉取/解析失败: {e}')

    if not all_channels:
        raise RuntimeError(f'所有直播源均未取到有效数据: {errors}')

    raw_count = len(all_channels)

    if cfg.get('logo', {}).get('backfill_from_sources', True):
        filled = _backfill_logos(all_channels)
        logger.info(f'[live_source] 跨源补台标 {filled} 条')

    # 顺序很重要：先测活，再按频道去重。
    # 反过来的话「每台只留 1 条」就没备线可换，主线路一死整台就消失。
    candidates = _dedupe_urls(all_channels)
    channels = candidates
    dropped = []
    health_stats = {'enabled': False}
    if (cfg.get('check') or {}).get('enabled'):
        from tasks import live_health
        # 与 live_check 共用一把锁：两轮测活同时跑会把失败次数重复累加，瞬间把好线判死
        _lock = live_health.acquire_check_lock(cfg)
        if _lock is None:
            raise RuntimeError('另一轮测活（live_check）正在运行，本次聚合放弃，避免重复累加失败次数')
        try:
            channels, dropped, health_stats = live_health.check_channels(candidates, cfg)
        finally:
            live_health.release_check_lock(_lock)
        logger.info(f'[live_source] 测活后保留 {len(channels)} 条，剔除 {len(dropped)} 条')
        # 大面积判死守卫：手机/家用宽带很容易因为并发探测把网络打满而“假死”。
        # 这里抽 20 条被判死的线慢速单测一遍，如果过半能通，就认定本轮是本机网络问题，
        # 直接中止，不用这份残缺结果覆盖上一份 m3u。
        max_ratio = float((live_health.health_cfg(cfg) or {}).get('max_drop_ratio') or 0)
        total_checked = len(candidates) or 1
        ratio = len(dropped) / total_checked
        if max_ratio > 0 and len(candidates) >= 20 and ratio > max_ratio:
            sample = random.sample(dropped, min(20, len(dropped)))
            alive = 0
            for ch in sample:
                try:
                    if live_health.probe(ch['url'], cfg).get('ok'):
                        alive += 1
                except Exception:  # noqa
                    pass
            logger.warning(f'[live_source] 本轮剔除 {len(dropped)}/{total_checked} = {ratio:.0%} '
                           f'超过 max_drop_ratio={max_ratio:.0%}，慢速复核样本 {len(sample)} 条中 '
                           f'{alive} 条还能通')
            if alive * 2 >= len(sample):
                raise RuntimeError(
                    f'测活结果异常：剔除率 {ratio:.0%}，但复核样本 {alive}/{len(sample)} 条可播放，'
                    f'判定为本机网络/并发问题，中止本次聚合，不覆盖已有 m3u')

    channels = _dedupe(channels, cfg.get('dedupe') or {})
    deduped_count = len(channels)
    dropped_count = len(dropped)
    logger.info(f'[live_source] 去重后 {len(channels)} 条（原始 {raw_count} 条）')

    out_cfg = cfg.get('output') or {}
    # 防止某次只成功一两个源时，用残缺列表把上一份好数据覆盖掉。
    # 默认只告警照写（保留 .bak），因为「少而死」比「多但全死」好；需要严格拦截时配 abort。
    min_final_count = int(out_cfg.get('min_final_count') or 0)
    if min_final_count and len(channels) < min_final_count:
        msg = (
            f'聚合结果只有 {len(channels)} 条，低于 output.min_final_count={min_final_count}；'
            f'失败源: {errors}'
        )
        if str(out_cfg.get('min_final_count_action') or 'warn').lower() == 'abort':
            raise RuntimeError(msg + f'，不覆盖 {out_cfg.get("m3u") or "m3u/live_merged.m3u"}')
        logger.warning(f'[live_source] {msg}（照常写入，旧文件已备份为 .bak）')

    # 第二道守卫：缩水太多时，把上一份 m3u 里没被判死的线路并回来（详见 _merge_previous_ok）
    if (cfg.get('check') or {}).get('enabled'):
        try:
            from tasks import live_health as _lh
            channels = _merge_previous_ok(channels, out_cfg, cfg, _lh)
        except Exception as e:  # noqa
            logger.warning(f'[live_source] 回补上一份 m3u 失败（忽略）: {e}')

    # 台标本地缓存：下载失败保留原 URL，不影响播放
    logo_stats = _cache_logos(channels, cfg, req_cfg)
    # EPG 本地缓存 + 按频道索引（供 /epg 接口使用）
    epg_url, epg_stats = _cache_epg(channels, cfg, req_cfg)

    channels = _group_channels(channels, cfg.get('group_order') or [])
    content = _render_m3u(channels, epg_url)

    out_m3u = FILES_DIR / (out_cfg.get('m3u') or 'm3u/live_merged.m3u')
    _write_atomic(out_m3u, content, backup=True)
    logger.info(f'[live_source] 已写入 {out_m3u}')

    # 被剔除线路清单，方便人工核查「剔得对不对」
    if health_stats.get('enabled') and not health_stats.get('degraded'):
        try:
            from tasks import live_health
            report = live_health.write_dead_report(cfg, live_health.load_ledger(cfg))
            logger.info(f'[live_source] 死链清单已更新 {report}')
        except Exception as e:  # noqa
            logger.warning(f'[live_source] 写死链清单失败: {e}')

    if out_cfg.get('mirror_local_txt', True) and out_cfg.get('local_txt'):
        local_txt = FILES_DIR / out_cfg['local_txt']
        _write_atomic(local_txt, content)
        logger.info(f'[live_source] 已同步兼容文件 {local_txt}')

    groups = {}
    for c in channels:
        groups[c.get('group') or '其他'] = groups.get(c.get('group') or '其他', 0) + 1

    # 产物清单（相对 FILES_DIR），方便脚本/前端判断某个产物是否已生成
    outputs = {'m3u': out_cfg.get('m3u') or 'm3u/live_merged.m3u'}
    if out_cfg.get('mirror_local_txt', True) and out_cfg.get('local_txt'):
        outputs['local_txt'] = out_cfg['local_txt']
    if out_cfg.get('meta'):
        outputs['meta'] = out_cfg['meta']
    epg_cfg = cfg.get('epg_cache') or {}
    if epg_cfg.get('enabled'):
        if epg_cfg.get('write_xml', True):
            outputs['epg_xml'] = str(epg_cfg.get('xml_file') or 'txt/e.xml').strip('/')
        outputs['epg_index'] = str(epg_cfg.get('index_file') or 'json/epg_index.json').strip('/')
    if (cfg.get('logo') or {}).get('cache_local'):
        outputs['logo_dir'] = str((cfg.get('logo') or {}).get('dir') or 'm3u/logo').strip('/')
    outputs['epg_url'] = epg_url

    meta = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'raw_count': raw_count,
        'deduped_count': deduped_count,
        'final_count': len(channels),
        'removed_count': raw_count - len(channels),
        'dropped_by_dedupe': max(0, len(candidates) - dropped_count - len(channels)),
        'dropped_by_url_dup': raw_count - len(candidates),
        'dropped_by_check': dropped_count,
        'health_check': {k: v for k, v in (health_stats or {}).items() if k != 'detail'},
        'dropped_detail': (health_stats or {}).get('detail') or [],
        'groups': groups,
        'sources': source_stats,
        'logo_cache': logo_stats,
        'epg_cache': epg_stats,
        'outputs': outputs,
        'errors': errors,
    }
    if out_cfg.get('meta'):
        _write_atomic(FILES_DIR / out_cfg['meta'], json.dumps(meta, ensure_ascii=False, indent=2))

    return meta


def main(task_id='live_source', *args, config_path=None, **kwargs):
    print(f'=========task_id:{task_id},args:{args},kwargs:{kwargs}=========')
    try:
        meta = run(Path(config_path) if config_path else CONFIG_PATH)
        result = (
            f'直播源聚合完成: 原始{meta["raw_count"]}条 -> 最终{meta["final_count"]}条'
            f'，测活剔除{meta["dropped_by_check"]}条'
        )
        if meta.get('health_check', {}).get('probed'):
            result += (f'（探测{meta["health_check"]["probed"]}条，'
                       f'熔断host {len(meta["health_check"].get("dead_hosts") or [])} 个，'
                       f'续期{meta["health_check"].get("renewed", 0)}条）')
        if meta['errors']:
            result += f'；失败源: {"; ".join(meta["errors"])}'
        logger.info(f'[live_source] {result}')
        return result
    except Exception as e:  # noqa
        logger.exception(f'[live_source] 任务失败: {e}')
        return f'直播源聚合失败: {e}'


if __name__ == '__main__':
    # 支持自定义配置：python -m tasks.live_source path/to/live_sources.json
    custom = sys.argv[1] if len(sys.argv) > 1 else None
    print(main(config_path=custom))
