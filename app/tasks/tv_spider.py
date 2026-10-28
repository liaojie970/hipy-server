#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : tv_spider.py
# Author: DaShenHan&道长-----先苦后甜，任凭晚风拂柳颜------
# Date  : 2024/2/20
# 电视直播爬虫：拉 ssili126/tv 的 txt 源，写到 t4/files/txt/
#
# 改造要点（配合 tasks/live_health.py 的线路体检）：
#   1. 默认**不再覆盖 txt/mytv.txt**（配置 write_mytv，默认 false）：
#      直播页现在读 m3u/live_merged.m3u，mytv.txt 只留给旧配置，不该被每 4 小时无脑覆盖；
#   2. 阈值不达标 / 拉取失败时**保留旧文件**，只在日志里说清楚原因；
#   3. 写入改为原子替换 + 备份 .bak，避免写一半留下残file；
#   4. `drop_auth_urls` 支持按正则剔除带 ?Authinfo= / token= 这类会过期的线路；
#   5. 所有参数可在 t4/files/json/tv_spider.json 里覆盖（文件不存在则用默认值）。

import json
import os
import re
from pathlib import Path

import requests

try:
    from core.logger import logger
except Exception:  # 允许脱离 hipy 环境单独调试
    import logging

    logger = logging.getLogger(__name__)

try:
    from utils.httpapi import getGitContents
except Exception:  # noqa
    getGitContents = None

APP_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = APP_DIR / 't4' / 'files'
CONFIG_PATH = FILES_DIR / 'json' / 'tv_spider.json'

DEFAULTS = {
    'enabled': True,
    'repo': 'ssili126/tv',
    'github_proxy': '',
    # 按顺序尝试的 GitHub 加速前缀（空串=直连），前一个失败就换下一个
    'github_mirrors': ['', 'https://gh-proxy.com/', 'https://ghfast.top/'],
    'github_proxy_fallback': True,
    'timeout': 8,
    'min_tv_lines': 200,
    'min_mytv_lines': 200,
    'write_tv': True,
    'write_mytv': False,
    'drop_auth_urls': True,
    'drop_patterns': [
        r'[?&](Authinfo|authinfo|token|access_token|authid)=' ,
    ],
    'keep_backup': True,
}

def _mirror_prefixes(cfg):
    """GitHub 加速前缀候选列表：github_mirrors 优先，其次兼容老配置的 github_proxy。"""
    prefixes = []
    raw = cfg.get('github_proxy') or ''
    for item in cfg.get('github_mirrors') or []:
        if isinstance(item, str):
            prefixes.append(item)
    if isinstance(raw, str) and raw:
        prefixes.insert(0, raw)
    elif isinstance(raw, (list, tuple)):
        prefixes = [x for x in raw if isinstance(x, str)] + prefixes
    if cfg.get('github_proxy_fallback', True):
        for extra in ('', 'https://gh-proxy.com/', 'https://ghfast.top/'):
            prefixes.append(extra)
    # 去重但保留顺序
    seen, out = set(), []
    for p in prefixes:
        p = (p or '').strip()
        if not p.endswith('/') and p:
            p += '/'
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    # 直连放最后，避免国内网络先卡 8 秒
    if '' in out:
        out.remove('')
        out.append('')
    return out


def _fetch_with_mirrors(url, prefixes, timeout):
    """依次用各加速前缀请求同一个地址，任一成功即返回文本；全失败抛最后一个异常。"""
    last_err = None
    tried = []
    for prefix in prefixes:
        target = prefix + url
        tried.append(prefix or '(直连)')
        try:
            r = requests.get(target, timeout=timeout)
            r.raise_for_status()
            if r.text and r.text.strip():
                return r.text
            last_err = RuntimeError(f'空响应: {target}')
        except Exception as e:  # noqa
            last_err = e
    raise RuntimeError(f'所有镜像均失败({",".join(tried)}): {last_err}')


_COMPILED = (None, None)  # (patterns_key, compiled)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_PATH.exists():
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding='utf-8')) or {})
    except Exception as e:  # noqa
        logger.warning(f'[tv_spider] 配置读取失败，使用默认值: {e}')
    return cfg


def _patterns(cfg: dict):
    global _COMPILED
    key = tuple(p for p in (cfg.get('drop_patterns') or []) if p)
    if _COMPILED[0] != key:
        _COMPILED = (key, re.compile('|'.join(key), re.I) if key else None)
    return _COMPILED[1]


def filter_content(text: str, cfg: dict) -> tuple:
    """剔除会过期的鉴权线路，返回 (过滤后文本, 剔除行数)。"""
    if not cfg.get('drop_auth_urls'):
        return text, 0
    pattern = _patterns(cfg)
    if not pattern:
        return text, 0
    kept, dropped = [], 0
    for line in text.splitlines():
        if pattern.search(line):
            dropped += 1
            continue
        kept.append(line)
    return '\n'.join(kept), dropped


def _write_atomic(path: Path, content: str, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if cfg.get('keep_backup') and path.exists():
        try:
            path.with_name(path.name + '.bak').write_bytes(path.read_bytes())
        except Exception:  # noqa
            pass
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(content, encoding='utf-8', newline='\n')
    os.replace(tmp, path)


def _save(name: str, text: str, min_lines: int, cfg: dict) -> str:
    """写文件：行数不达标就不动旧文件。返回可读的结果描述。"""
    path = FILES_DIR / 'txt' / name
    filtered, dropped = filter_content(text, cfg)
    items = [ln for ln in filtered.splitlines() if ln.strip()]
    tail = f'（剔除鉴权线路{dropped}行）' if dropped else ''
    if len(items) < min_lines:
        return f'本次未写入{name}[有效行数{len(items)}不足{min_lines}]{tail}'
    if not ('CCTV' in filtered or '卫视' in filtered):
        return f'本次未写入{name}[内容不含cctv或卫视]{tail}'
    _write_atomic(path, filtered, cfg)
    return f'本次成功写入{name}[{len(items)}行]{tail}'


def main(task_id='tv_spider', mytv_count=None, tv_count=None):
    print(f'=========task_id:{task_id}')
    cfg = load_config()
    if not cfg.get('enabled'):
        return f'{task_id}: 已在 {CONFIG_PATH.name} 中禁用，跳过'
    if not getGitContents:
        return f'{task_id}: utils.httpapi 不可用，跳过'

    mytv_count = int(mytv_count or cfg['min_mytv_lines'])
    tv_count = int(tv_count or cfg['min_tv_lines'])
    files = getGitContents(cfg['repo'], '', '')
    txt_files = [f for f in files if str(f['name']).endswith('.txt') and f.get('type') == 'file']
    txt_files = [{
        'rule': re.sub(r'\.txt$', '', f['name']),
        'name': f['name'],
        'size': f"{round(f['size'] / 1024, 2)}kb",
        'url': f['download_url'],
    } for f in txt_files]

    mirrors = _mirror_prefixes(cfg)
    contents, my_content, error = [], '', []
    for txt_file in txt_files:
        try:
            text = _fetch_with_mirrors(txt_file['url'], mirrors, float(cfg['timeout']))
            text = text.strip()
            contents.append(text)
            if txt_file['name'] == 'itvlist.txt':
                my_content = text
        except Exception as e:  # noqa
            error.append(txt_file['name'])
            logger.warning(f'[tv_spider] 未能获取 {txt_file["name"]}: {e}')

    if not contents:
        return f'{task_id}: 所有源均拉取失败（{",".join(error)}），保留旧文件'

    content = '\n'.join(contents)
    results = [f'爬取直播文件行数:{len(content.splitlines())}']
    if error:
        results.append(f'未能获取{",".join(error)}等文件内容')

    if cfg.get('write_tv'):
        results.append(_save('tv.txt', content, tv_count, cfg))
    else:
        results.append('write_tv=false，跳过 tv.txt')

    if cfg.get('write_mytv'):
        if my_content:
            results.append(_save('mytv.txt', my_content, mytv_count, cfg))
        else:
            results.append('本次未写入mytv.txt[未取到itvlist.txt]')
    else:
        results.append('write_mytv=false，保持 mytv.txt 不变（直播页用 m3u/live_merged.m3u）')

    result = ', '.join(results)
    logger.info(f'[tv_spider] {result}')
    print(result)
    return result


if __name__ == '__main__':
    main('tv_spider')
