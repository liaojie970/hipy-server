#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直播线路体检（测活 / 台账 / 剔除）

设计目标：解决「上游源里大量死线路 + 带 Authinfo token 的线路随时失效」
这类源质量问题。核心是**三级测活 + 线路台账 + 软删除状态机**：

    拉播放列表 -> 必须含 #EXTM3U -> 拉首个分片，校验 200 且非空

工作方式：
    - 每次聚合（tasks.live_source）里做「重建前体检」；
    - 独立定时任务 tasks.live_health.main 每 6 小时对**已生成的 m3u** 做复查，
      不重新拉上游，只把新判死的线路剔掉。

台账（默认 t4/files/json/live_health.json）按 **归一化 URL** 记录
first_seen / last_ok / fail_count / state / cooldown_until 等，实现：
    - 连续失败才判死（404/403 欠 2 次，超时/502 欠 3 次），抵抗网络抖动；
    - 判死后冷却 N 小时不再探测、不再输出；
    - 冷却到期自动复测，给源一次复活机会；
    - 台账损坏/缺失时**整体降级为全放行**，绝不因台账把直播搞挂。

命令行（在 app/ 目录下）：
    python -m tasks.live_health --dry-run --limit 60   # 只探测，不写台账/不改 m3u
    python -m tasks.live_health --recheck              # 复查并重写 m3u
    python -m tasks.live_health --stats                # 只看台账统计
"""

import argparse
import copy
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests

try:
    from core.logger import logger
except Exception:  # 允许脱离 hipy 环境单独调试
    import logging

    logger = logging.getLogger(__name__)

try:
    from utils.define import DEFAULT_USER_AGENT
except Exception:  # noqa
    DEFAULT_USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
    )

APP_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = APP_DIR / 't4' / 'files'
CONFIG_PATH = FILES_DIR / 'json' / 'live_sources.json'

# 结果分类
KIND_OK = 'ok'
KIND_AUTH = 'auth_expired'        # 鉴权失败（token 过期 / 无权限）
KIND_GONE = 'source_gone'         # 路径或主机已下线
KIND_UNREACHABLE = 'unreachable'  # 超时 / 502 / SSL，大概率是网络
KIND_HTTP = 'http_error'          # 其它 >=400
KIND_SEGMENT = 'segment_failed'   # 播放列表正常但分片拉不到
KIND_UNTESTED = 'untestable'      # rtmp/udp 等无法用 HTTP 测活

# 判定为「硬失败」的类别：欠 2 次即判死
HARD_KINDS = (KIND_AUTH, KIND_GONE, KIND_HTTP, KIND_SEGMENT)
# 判定为「软失败」的类别：欠 3 次才判死（多为网络抖动/代理问题）
SOFT_KINDS = (KIND_UNREACHABLE,)

DEFAULT_AUTH_PARAMS = [
    'Authinfo', 'authinfo', 'authInfo', 'token', 'access_token', 'accesstoken',
    'authid', 'sign', 'signature', 'expires', 'expire',
]

_lock = threading.Lock()
_session_local = threading.local()


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def check_cfg(cfg: dict) -> dict:
    c = dict(cfg.get('check') or {})
    c.setdefault('enabled', True)
    c.setdefault('deep', True)
    c.setdefault('timeout', 8)
    c.setdefault('workers', 16)
    c.setdefault('keep_untestable', True)
    c.setdefault('keep_suspect', True)
    c.setdefault('host_sample', 3)
    c.setdefault('host_breaker', True)
    c.setdefault('probe_per_batch', 2)
    c.setdefault('batch_lcp_min', 12)
    c.setdefault('segment_bytes', 1)
    c.setdefault('renew_by_redirect', False)
    c.setdefault('auth_params', DEFAULT_AUTH_PARAMS)
    return c


def health_cfg(cfg: dict) -> dict:
    h = dict(cfg.get('health') or {})
    h.setdefault('enabled', True)
    h.setdefault('file', 'json/live_health.json')
    h.setdefault('dead_report', 'm3u/live_merged.dead.txt')
    h.setdefault('dead_after_hard', 2)
    h.setdefault('dead_after_soft', 3)
    h.setdefault('cooldown_hours', 24)
    h.setdefault('history_days', 30)
    # 单轮剔除比例上限: 超过它就认为“本轮网络异常”而不是“线路全死”,
    # 放弃本轮结论(回滚台账、不改 m3u), 防止误杀大批还能播的线路
    h.setdefault('max_drop_ratio', 0.5)
    return h


# --------------------------------------------------------------------------- #
# 互斥锁: 防止两轮测活同时跑(重复累加失败次数会瞬间把好线判死)
# --------------------------------------------------------------------------- #
def _lock_path(cfg: dict) -> Path:
    return FILES_DIR / 'json' / '.live_check.lock'


def acquire_check_lock(cfg: dict):
    """非阻塞拿锁, 成功返回文件句柄, 失败返回 None。Windows(无 fcntl)直接放行。"""
    try:
        import fcntl  # noqa
    except ImportError:
        return 'no-lock'
    path = _lock_path(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, 'a+')
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        try:
            fh.close()
        except Exception:  # noqa
            pass
        return None
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(f'{os.getpid()} {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
        fh.flush()
    except Exception:  # noqa
        pass
    return fh


def release_check_lock(fh) -> None:
    if not fh or fh == 'no-lock':
        return
    try:
        import fcntl  # noqa
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:  # noqa
        pass
    try:
        fh.close()
    except Exception:  # noqa
        pass


# --------------------------------------------------------------------------- #
# 台账
# --------------------------------------------------------------------------- #
def ledger_path(cfg: dict) -> Path:
    return FILES_DIR / str(health_cfg(cfg)['file']).strip('/')


def load_ledger(cfg: dict) -> dict:
    path = ledger_path(cfg)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('entries'), dict):
            raise ValueError('台账格式不正确')
        return data
    except FileNotFoundError:
        return {'version': 1, 'entries': {}}
    except Exception as e:  # noqa
        # 台账坏了不能影响直播，直接降级为「空台账 = 全放行」
        logger.warning(f'[live_health] 台账读取失败({path}): {e}，本次降级为全放行')
        return {'version': 1, 'entries': {}, 'degraded': True}


def save_ledger(cfg: dict, ledger: dict) -> None:
    if ledger.get('degraded'):
        logger.warning('[live_health] 台账处于降级状态，本次不写回，避免覆盖可恢复的旧数据')
        return
    h = health_cfg(cfg)
    path = ledger_path(cfg)
    now = time.time()
    keep_days = float(h['history_days'] or 0)
    if keep_days > 0:
        limit = now - keep_days * 86400
        entries = ledger.get('entries') or {}
        for key in [k for k, v in entries.items()
                    if float(v.get('last_check_ts') or 0) < limit and v.get('state') != 'dead']:
            entries.pop(key, None)
    ledger['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, path)


def url_key(url: str, cfg: dict) -> str:
    """归一化 URL：去掉鉴权类查询参数 + 排序，让「同一张票换了个 token」仍算同一条线。"""
    auth_params = {p.lower() for p in (check_cfg(cfg).get('auth_params') or [])}
    try:
        p = urlparse(url)
    except Exception:  # noqa
        return url
    query = []
    for part in (p.query or '').split('&'):
        if not part:
            continue
        name = part.split('=', 1)[0]
        if name.lower() in auth_params:
            continue
        query.append(part)
    query.sort()
    netloc = p.netloc.lower()
    return urlunparse((p.scheme.lower(), netloc, p.path, '', '&'.join(query), ''))


def _token_of(url: str) -> str:
    try:
        query = urlparse(url).query
    except Exception:  # noqa
        return ''
    for part in (query or '').split('&'):
        if '=' not in part:
            continue
        k, v = part.split('=', 1)
        if k.lower() in ('authinfo', 'token', 'access_token', 'accesstoken'):
            return v
    return ''


def _mac_of(url: str) -> str:
    try:
        query = urlparse(url).query
    except Exception:  # noqa
        return ''
    for part in (query or '').split('&'):
        if '=' not in part:
            continue
        k, v = part.split('=', 1)
        if k.lower() == 'mac':
            return v
    return ''


def token_fingerprint(url: str) -> str:
    """兼容旧接口：同 host + 同 mac + 同 token 视为同一张票。"""
    token = _token_of(url)
    if not token:
        return ''
    return f'{urlparse(url).netloc.lower()}|{_mac_of(url)}|{token}'


def build_batches(channels: list, cfg: dict) -> tuple:
    """把「同一张票」的线路折叠成批次。

    上游很多源是同一张会话票 + 每频道不同后缀（如 `Authinfo=<同一段前缀>...`），
    所以按 (host, mac) 分组后取 token 的**公共前缀**分桶，整桶算一批。
    注意：批次结论**只用于失败判定**（票过期/主机下线是整批一起死），
    批次里某条线路自己的路径失效仍需单独探测。
    """
    c = check_cfg(cfg)
    lcp_min = max(4, int(c.get('batch_lcp_min') or 12))
    groups, plain = {}, []
    for ch in channels:
        token = _token_of(ch['url'])
        if not token:
            plain.append(ch)
            continue
        host = urlparse(ch['url']).netloc.lower()
        groups.setdefault((host, _mac_of(ch['url'])), []).append((token, ch))

    batches = {}
    for (host, mac), items in groups.items():
        lcp = os.path.commonprefix([t for t, _ in items]) if len(items) > 1 else ''
        if len(items) > 1 and len(lcp) >= lcp_min:
            buckets = {lcp: items}
        else:
            buckets = {}
            for token, ch in items:
                buckets.setdefault(token, []).append((token, ch))
        for key, arr in buckets.items():
            fp = f'{host}|{mac}|{key[:12]}|{len(key)}'
            batches[fp] = [ch for _, ch in arr]
    return batches, plain


def get_session(trust_env: bool) -> requests.Session:
    session = getattr(_session_local, 'session', None)
    if session is None or getattr(_session_local, 'trust_env', None) != trust_env:
        session = requests.Session()
        session.trust_env = trust_env
        session.headers.update({'User-Agent': DEFAULT_USER_AGENT, 'Accept': '*/*'})
        _session_local.session = session
        _session_local.trust_env = trust_env
    return session


def _env_proxy_configured() -> bool:
    keys = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')
    return any(os.environ.get(k) for k in keys)


# --------------------------------------------------------------------------- #
# 探测
# --------------------------------------------------------------------------- #
def _classify_status(status: int) -> str:
    if status in (401, 403):
        return KIND_AUTH
    if status == 404:
        return KIND_GONE
    if status in (408, 429, 500, 502, 503, 504):
        return KIND_UNREACHABLE
    return KIND_HTTP


def _playlist_lines(text: str) -> list:
    return [ln.strip() for ln in (text or '').splitlines()
            if ln.strip() and not ln.strip().startswith('#')]


def _probe_stream(url: str, cfg: dict, trust_env: bool, depth: int = 0) -> dict:
    """拉播放列表（含 #EXTM3U 校验），可选拉首个分片。返回结果 dict。"""
    c = check_cfg(cfg)
    timeout = float(c['timeout'])
    session = get_session(trust_env)
    try:
        r = session.get(url, timeout=timeout, stream=True, allow_redirects=True)
        status = r.status_code
        if status >= 400:
            r.close()
            return {'ok': False, 'status': status, 'kind': _classify_status(status), 'detail': f'HTTP {status}'}
        body = b''
        for chunk in r.iter_content(2048):
            body += chunk
            if len(body) >= 2048:
                break
        r.close()
    except requests.exceptions.Timeout:
        return {'ok': False, 'status': 'timeout', 'kind': KIND_UNREACHABLE, 'detail': '请求超时'}
    except Exception as e:  # noqa
        return {'ok': False, 'status': type(e).__name__, 'kind': KIND_UNREACHABLE, 'detail': str(e)[:120]}

    text = body.decode('utf-8', 'replace')
    is_playlist = '#EXTM3U' in text or '#EXTINF' in text
    if not c['deep'] or not is_playlist:
        return {'ok': True, 'status': status, 'kind': KIND_OK, 'detail': 'HTTP 200'}

    segs = _playlist_lines(text)
    if not segs:
        # 主播放列表里没有子列表（master playlist），再下钻一层
        variants = [ln.split(':', 1)[1] for ln in text.splitlines() if ln.startswith('#EXT-X-STREAM-INF')]
        if not variants and depth < 1:
            alt = [ln.split('URI="', 1)[1].rstrip('"') for ln in text.splitlines() if 'URI="' in ln]
            variants = alt
        if variants and depth < 1:
            return _probe_stream(urljoin(url, variants[0].split(',')[0]), cfg, trust_env, depth + 1)
        return {'ok': False, 'status': status, 'kind': KIND_SEGMENT, 'detail': '播放列表无分片'}

    seg_url = urljoin(url, segs[0])
    nbytes = max(1, int(c['segment_bytes']))

    def _seg(use_range: bool, want: int):
        rs = session.get(seg_url, timeout=timeout, stream=True, allow_redirects=True,
                         headers={'Range': f'bytes=0-{want - 1}'} if use_range else None)
        st = rs.status_code
        got = 0
        if st < 400:
            for chunk in rs.iter_content(2048):
                got = len(chunk)
                break
        rs.close()
        return st, got

    try:
        sstatus, got = _seg(True, nbytes)
        # 有些 CDN 对 bytes=0-0 会回 206 + 空体，或干脆 416；去掉 Range 再确认一次，避免误杀
        if got <= 0 and (sstatus < 400 or sstatus in (400, 416)):
            sstatus, got = _seg(False, max(1024, nbytes))
    except requests.exceptions.Timeout:
        return {'ok': False, 'status': 'timeout', 'kind': KIND_UNREACHABLE, 'detail': '分片超时'}
    except Exception as e:  # noqa
        return {'ok': False, 'status': type(e).__name__, 'kind': KIND_UNREACHABLE, 'detail': f'分片 {e}'[:120]}

    if sstatus >= 400:
        return {'ok': False, 'status': sstatus, 'kind': _classify_status(sstatus), 'detail': f'分片 HTTP {sstatus}'}
    if got <= 0:
        return {'ok': False, 'status': sstatus, 'kind': KIND_SEGMENT, 'detail': '分片内容为空'}
    return {'ok': True, 'status': status, 'kind': KIND_OK, 'detail': '列表+分片均正常'}


def probe(url: str, cfg: dict) -> dict:
    """直连优先，确实配了代理再试一次（与 live_source 的取源逻辑保持一致）。"""
    if not str(url).lower().startswith(('http://', 'https://')):
        return {'ok': bool(check_cfg(cfg)['keep_untestable']), 'status': '-',
                'kind': KIND_UNTESTED, 'detail': '非 http(s) 协议'}
    trust_env_options = (False, True) if _env_proxy_configured() else (False,)
    last = None
    for trust_env in trust_env_options:
        res = _probe_stream(url, cfg, trust_env)
        if res['ok']:
            return res
        last = res
        # 已经有明确的服务器响应（4xx/分片问题）就没必要再换网络重试
        if res['kind'] in HARD_KINDS:
            return res
    return last or {'ok': False, 'status': 'unknown', 'kind': KIND_UNREACHABLE, 'detail': '未知错误'}


def _strip_auth(url: str, cfg: dict) -> str:
    auth_params = {p.lower() for p in (check_cfg(cfg).get('auth_params') or [])}
    try:
        p = urlparse(url)
    except Exception:  # noqa
        return url
    parts = [x for x in (p.query or '').split('&') if x and x.split('=', 1)[0].lower() not in auth_params]
    return urlunparse((p.scheme, p.netloc, p.path, '', '&'.join(parts), ''))


_AUTH_PARAM_RE = re.compile(r'([?&])(Authinfo|authinfo|token|access_token)=[^&]*', re.I)


def _try_renew(url: str, cfg: dict) -> str:
    """可续期性探测：去掉票重放，若 3xx 的 Location 里带上了新票，就认为「可续期」。

    默认关闭（check.renew_by_redirect=false）。只在确实观察到这种源后再打开。
    """
    if not check_cfg(cfg).get('renew_by_redirect'):
        return ''
    session = get_session(False)
    probe_url = _strip_auth(url, cfg)
    try:
        r = session.get(probe_url, timeout=float(check_cfg(cfg)['timeout']),
                        allow_redirects=False, stream=True)
        loc = r.headers.get('Location') or ''
        r.close()
    except Exception:  # noqa
        return ''
    if not loc or not _AUTH_PARAM_RE.search(loc):
        return ''
    new_url = urljoin(url, loc)
    res = probe(new_url, cfg)
    return new_url if res['ok'] else ''


def _classify_batch(batch_urls: list, cfg: dict) -> dict:
    """对同一张票的一组线路做判定：抽样探测 + 无票对照，区分「票过期」和「源下线」。"""
    c = check_cfg(cfg)
    reps = batch_urls[:max(1, int(c['probe_per_batch']))]
    results = [probe(u, cfg) for u in reps]
    ok_res = next((r for r in results if r['ok']), None)
    if ok_res:
        return {'ok': True, 'result': ok_res, 'renewed_url': ''}

    worst = results[0]
    # 有票/无票都同样失败 => 不是票的问题，是源整体不可用
    control_url = _strip_auth(reps[0], cfg)
    control = probe(control_url, cfg) if control_url != reps[0] else None
    if control is not None:
        if control['ok'] and not worst['ok']:
            # 无票反而能播？把它当成可续期/免票线路
            return {'ok': True, 'result': control, 'renewed_url': control_url}
        if control['kind'] == worst['kind'] or (not control['ok'] and control['kind'] in HARD_KINDS
                                                and worst['kind'] in HARD_KINDS):
            renewed = _try_renew(reps[0], cfg)
            if renewed:
                return {'ok': True, 'result': {'ok': True, 'status': 200, 'kind': KIND_OK,
                                               'detail': '续期成功'}, 'renewed_url': renewed}
            return {'ok': False, 'result': control, 'renewed_url': ''}
    return {'ok': False, 'result': worst, 'renewed_url': ''}


# --------------------------------------------------------------------------- #
# 状态机
# --------------------------------------------------------------------------- #
def _state_after(entry: dict, result: dict, cfg: dict) -> None:
    h = health_cfg(cfg)
    now = time.time()
    entry['last_check_ts'] = now
    entry['last_check'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))
    entry['last_status'] = str(result.get('status'))
    entry['last_kind'] = result.get('kind')
    entry['detail'] = result.get('detail')
    if result.get('ok'):
        entry['ok_count'] = int(entry.get('ok_count') or 0) + 1
        entry['fail_count'] = 0
        entry['consec_fail'] = 0
        entry['last_ok'] = entry['last_check']
        entry['state'] = 'ok'
        entry['reason'] = ''
        entry.pop('cooldown_until', None)
        return

    entry['fail_count'] = int(entry.get('fail_count') or 0) + 1
    entry['consec_fail'] = int(entry.get('consec_fail') or 0) + 1
    entry['last_fail'] = entry['last_check']
    kind = result.get('kind')
    need = int(h['dead_after_hard'] if kind in HARD_KINDS else h['dead_after_soft'])
    if entry['consec_fail'] >= max(1, need):
        entry['state'] = 'dead'
        entry['reason'] = f'{kind}: {result.get("detail") or result.get("status")}'
        entry['cooldown_until'] = time.strftime(
            '%Y-%m-%d %H:%M:%S', time.localtime(now + float(h['cooldown_hours']) * 3600))
    else:
        entry['state'] = 'suspect'
        entry['reason'] = f'疑似({entry["consec_fail"]}/{need}) {kind}'


def _in_cooldown(entry: dict) -> bool:
    until = entry.get('cooldown_until')
    if entry.get('state') != 'dead' or not until:
        return False
    try:
        return time.mktime(time.strptime(until, '%Y-%m-%d %H:%M:%S')) > time.time()
    except Exception:  # noqa
        return False


def _should_keep(entry: dict, keep_suspect: bool) -> bool:
    state = entry.get('state')
    if state == 'ok':
        return True
    if state == 'suspect':
        return bool(keep_suspect)
    if state == 'dead':
        return False
    return True


def fingerprint(entry: dict) -> str:
    return f'{entry.get("host") or ""}|{entry.get("path") or ""}|{entry.get("mac") or ""}'


def _entry_for(ledger: dict, url: str, cfg: dict, channel: dict = None) -> dict:
    key = url_key(url, cfg)
    entry = ledger['entries'].get(key)
    if entry is None:
        p = urlparse(url)
        q = {}
        for part in (p.query or '').split('&'):
            if '=' in part:
                k, v = part.split('=', 1)
                q[k.lower()] = v
        entry = {
            'url': url, 'url_key': key, 'host': p.netloc.lower(), 'path': p.path,
            'mac': q.get('mac', ''), 'state': 'new', 'ok_count': 0, 'fail_count': 0,
            'consec_fail': 0, 'first_seen': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        ledger['entries'][key] = entry
    if channel:
        entry['name'] = channel.get('name') or entry.get('name') or ''
        entry['group'] = channel.get('group') or entry.get('group') or ''
    entry['url'] = url
    return entry


# --------------------------------------------------------------------------- #
# 对外：测活主流程
# --------------------------------------------------------------------------- #
def check_channels(channels: list, cfg: dict, ledger: dict = None, dry_run: bool = False) -> tuple:
    """对频道列表做测活，返回 (kept, dropped, stats)。

    - 同票折叠：同一张票（host+mac+token 公共前缀）的线路只抽 2 条探测，
      批次判定失败时整批沿用结论（票过期/主机下线是整批一起死）；
    - 主机级熔断：某 host 抽样全死则跳过该 host 剩余线路（可关）；
    - 判定「死」的线路进冷却期，本次不输出；未达失败阈值仍输出（keep_suspect）；
    - dry_run=True：阈值降为 1 次失败即算「会被剔除」，且不写台账。
    """
    c = check_cfg(cfg)
    h = health_cfg(cfg)
    ledger = ledger if ledger is not None else load_ledger(cfg)
    if ledger.get('degraded'):
        logger.warning('[live_health] 台账降级，本次跳过测活（全放行）')
        return list(channels), [], {'enabled': False, 'degraded': True,
                                    'kept': len(channels), 'dropped': 0, 'detail': []}

    cfg_run = cfg
    if dry_run:
        cfg_run = dict(cfg)
        cfg_run['health'] = dict(h)
        cfg_run['health']['dead_after_hard'] = 1
        cfg_run['health']['dead_after_soft'] = 1

    workers = max(1, int(c['workers']))
    per = max(1, int(c['probe_per_batch']))
    testable, untestable = [], []
    for ch in channels:
        (testable if str(ch.get('url', '')).lower().startswith(('http://', 'https://'))
         else untestable).append(ch)

    t0 = time.time()
    logger.info(f'[live_health] 开始测活：{len(testable)} 条待测，{len(untestable)} 条非 http(s)，并发 {workers}')

    # 1) URL 去重后折叠同票批次
    uniq, seen = [], set()
    for ch in testable:
        url = ch['url']
        if url in seen:
            continue
        seen.add(url)
        uniq.append(ch)

    batches, plain = build_batches(uniq, cfg)
    fp_of = {}
    phase1 = list(plain)
    for fp, urls in batches.items():
        for ch in urls:
            fp_of[ch['url']] = fp
        phase1.extend(urls[:per])
    shadow = {ch['url']: fp for fp, urls in batches.items() for ch in urls[per:]}
    logger.info(f'[live_health] 折叠后首批需探测 {len(phase1)} 条'
                f'（同票批次 {len(batches)} 组，待定线路 {len(shadow)} 条）')

    results = {}

    def _run(chs):
        if not chs:
            return
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(probe, ch['url'], cfg): ch for ch in chs}
            done = 0
            for fut in as_completed(futures):
                ch = futures[fut]
                try:
                    results[ch['url']] = fut.result()
                except Exception as e:  # noqa
                    results[ch['url']] = {'ok': False, 'status': 'error',
                                          'kind': KIND_UNREACHABLE, 'detail': str(e)[:120]}
                done += 1
                if done % 50 == 0:
                    alive = sum(1 for r in results.values() if r['ok'])
                    logger.info(f'[live_health] 探测进度 {done}/{len(chs)}，存活 {alive}')

    # 2) 主机级抽样熔断
    by_host = {}
    for ch in phase1:
        by_host.setdefault(urlparse(ch['url']).netloc.lower(), []).append(ch)
    host_sample = max(1, int(c['host_sample']))
    sample, rest = [], []
    for host, items in by_host.items():
        sample.extend(items[:host_sample])
        rest.extend(items[host_sample:])

    _run(sample)

    dead_hosts = set()
    if c['host_breaker']:
        for host, items in by_host.items():
            sampled = [results.get(ch['url']) for ch in items[:host_sample]]
            sampled = [r for r in sampled if r]
            # 只有「整机连不上」（超时/连接失败/5xx/SSL）才熔断；
            # 404/403 是「服务器还活着，只是这条路径没了」，不能拿来做整机证据。
            if len(sampled) >= min(host_sample, len(items)) and all(
                    not r['ok'] and r['kind'] == KIND_UNREACHABLE for r in sampled):
                dead_hosts.add(host)
        if dead_hosts:
            logger.info(f'[live_health] 抽样整机不可达，熔断 {len(dead_hosts)} 个 host，'
                        f'跳过 {sum(1 for ch in rest if urlparse(ch["url"]).netloc.lower() in dead_hosts)} 条')
    _run([ch for ch in rest if urlparse(ch['url']).netloc.lower() not in dead_hosts])

    # 熔断 host 的真实失败样本，用来给该 host 下未探测的线路定性
    host_verdict = {}
    for host in dead_hosts:
        for ch in by_host.get(host, []):
            res = results.get(ch['url'])
            if res and not res['ok']:
                host_verdict[host] = res
                break

    # 3) 批次结论：代表线路全灭 -> 整批沿用（再做无票对照，区分票过期/源下线）
    batch_failed = {}
    for fp, urls in batches.items():
        if urlparse(urls[0]['url']).netloc.lower() in dead_hosts:
            continue
        reps = [results.get(ch['url']) for ch in urls[:per]]
        reps = [r for r in reps if r]
        if not reps or any(r['ok'] for r in reps):
            continue
        verdict = {'ok': False, 'result': reps[0], 'renewed_url': ''}
        if reps[0]['kind'] in (KIND_AUTH, KIND_GONE) and reps[0].get('status') not in ('skipped', 'timeout'):
            verdict = _classify_batch([ch['url'] for ch in urls], cfg)
        batch_failed[fp] = verdict

    # 4) 批次没失败的那部分，线路各自路径仍要单独验证
    phase2 = [ch for url, fp in shadow.items()
              if fp not in batch_failed and urlparse(url).netloc.lower() not in dead_hosts]
    missing = [ch for ch in phase1 if ch['url'] not in results]
    _run(missing + phase2)

    for ch in phase1:
        if ch['url'] not in results:
            hv = host_verdict.get(urlparse(ch['url']).netloc.lower())
            results[ch['url']] = dict(hv, detail=f'{hv.get("detail")}(host 熔断)') if hv else {
                'ok': False, 'status': 'skipped', 'kind': KIND_UNREACHABLE, 'detail': 'host 熔断跳过'}

    def verdict_for(url: str) -> dict:
        fp = fp_of.get(url) or shadow.get(url)
        if fp in batch_failed:
            return batch_failed[fp]['result']
        res = results.get(url)
        if res:
            return res
        hv = host_verdict.get(urlparse(url).netloc.lower())
        if hv:
            return dict(hv, detail=f'{hv.get("detail")}(host 熔断)')
        return {'ok': False, 'status': 'skipped', 'kind': KIND_UNREACHABLE, 'detail': '未探测'}

    # 5) 写台账 + 分流
    kept, dropped, detail = [], [], []
    renewed = {}
    for ch in testable:
        res = verdict_for(ch['url'])
        entry = _entry_for(ledger, ch['url'], cfg, ch)
        _state_after(entry, res, cfg_run)
        fp = fp_of.get(ch['url']) or shadow.get(ch['url'])
        new_url = (batch_failed.get(fp) or {}).get('renewed_url') if fp else ''
        if new_url:
            renewed[ch['url']] = new_url
            ch['url'] = new_url
            entry['renewed_url'] = new_url
        if _should_keep(entry, bool(c['keep_suspect'])):
            kept.append(ch)
        else:
            dropped.append(ch)
            detail.append({
                'name': ch.get('name'), 'group': ch.get('group'), 'url': ch.get('url'),
                'status': entry.get('last_status'), 'kind': entry.get('last_kind'),
                'reason': entry.get('reason'), 'consec_fail': entry.get('consec_fail'),
                'cooldown_until': entry.get('cooldown_until'),
            })

    kept.extend(untestable)
    order = {id(ch): i for i, ch in enumerate(channels)}
    kept.sort(key=lambda ch: order.get(id(ch), 0))

    stats = {
        'enabled': True,
        'probed': sum(1 for r in results.values() if r.get('status') != 'skipped'),
        'shadow': len(shadow),
        'batches': len(batches),
        'batch_failed': len(batch_failed),
        'dead_hosts': sorted(dead_hosts),
        'renewed': len(renewed),
        'kept': len(kept),
        'dropped': len(dropped),
        'elapsed': round(time.time() - t0, 1),
        'dry_run': dry_run,
        'detail': detail[:300],
    }
    logger.info(
        f'[live_health] 测活完成：探测{stats["probed"]}条/批次{len(batches)}组(失败{len(batch_failed)})，'
        f'停用host {len(dead_hosts)} 个，续期 {len(renewed)} 条，'
        f'保留 {len(kept)} 条，剔除 {len(dropped)} 条，耗时 {stats["elapsed"]}s'
    )
    if not dry_run and not ledger.get('degraded'):
        save_ledger(cfg, ledger)
    return kept, dropped, stats


# --------------------------------------------------------------------------- #
# 已生成 m3u 的复查（定时任务 live_check）
# --------------------------------------------------------------------------- #
def parse_m3u_channels(text: str) -> list:
    """轻量解析：EXITINF 块 -> [{name, group, url}]，保持原有块顺序。"""
    channels = []
    pending = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith('#EXTINF'):
            group = re.search(r'group-title="([^"]*)"', line)
            name = line.split(',')[-1].strip()
            pending = {'name': name, 'group': group.group(1) if group else '', 'url': ''}
            continue
        if line.startswith('#'):
            continue
        if pending is not None:
            pending['url'] = line
            channels.append(pending)
            pending = None
    return channels


def filter_m3u(text: str, dead_urls: set, renewed: dict) -> str:
    """按「死链集合」过滤 m3u；顺带把可续期的 URL 换掉。保留表头。"""
    header = None
    lines_out, block = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith('#EXTM3U') and header is None and not lines_out and not block:
            header = raw
            continue
        if line.startswith('#'):
            block.append(raw)
            continue
        url = renewed.get(line, line)
        if line in dead_urls:
            block = []
            continue
        lines_out.extend(block)
        lines_out.append(url)
        block = []
    if block:
        lines_out.extend(block)
    out = header or '#EXTM3U'
    if lines_out:
        out += '\n' + '\n'.join(lines_out)
    return out + '\n'


def write_dead_report(cfg: dict, ledger: dict) -> Path:
    path = FILES_DIR / str(health_cfg(cfg)['dead_report']).strip('/')
    rows = []
    for entry in (ledger.get('entries') or {}).values():
        if entry.get('state') != 'dead':
            continue
        rows.append(entry)
    rows.sort(key=lambda e: (e.get('name') or '', e.get('last_check') or ''))
    lines = ['# 已剔除的直播线路（连续失败判定为死链，冷却期后自动复测）',
             f'# 生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}    共 {len(rows)} 条', '']
    for e in rows:
        lines.append(
            f'[{e.get("last_check")}] {e.get("reason")} | 连续失败{e.get("consec_fail")}次 '
            f'| 冷却至 {e.get("cooldown_until")} | {e.get("group") or "-"} | {e.get("name") or "-"}')
        lines.append(f'    {e.get("url")}')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    os.replace(tmp, path)
    return path


def _write_m3u_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        bak = path.with_name(path.name + '.bak')
        try:
            bak.write_bytes(path.read_bytes())
        except Exception:  # noqa
            pass
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(content, encoding='utf-8', newline='\n')
    os.replace(tmp, path)


def recheck(cfg_path: Path = CONFIG_PATH, dry_run: bool = False, limit: int = 0) -> dict:
    """复查已生成的 m3u：只测活、不拉上游，把新判死的线路剔掉。"""
    cfg = load_config(cfg_path)
    h = health_cfg(cfg)
    if not h.get('enabled'):
        return {'ok': False, 'error': 'health.enabled=false，已关闭复查'}
    out_cfg = cfg.get('output') or {}
    m3u_rel = out_cfg.get('m3u') or 'm3u/live_merged.m3u'
    m3u_path = FILES_DIR / m3u_rel
    if not m3u_path.exists():
        return {'ok': False, 'error': f'找不到 {m3u_path}'}

    text = m3u_path.read_text(encoding='utf-8')
    channels = parse_m3u_channels(text)
    if limit > 0:
        channels = channels[:limit]
        logger.info(f'[live_check] --limit {limit}，只探测前 {len(channels)} 条')
    if not channels:
        return {'ok': False, 'error': 'm3u 里没有解析到频道'}

    ledger = load_ledger(cfg)
    locked = acquire_check_lock(cfg)
    if locked is None:
        logger.warning('[live_check] 上一轮测活还没结束，本轮跳过（避免重复累加失败次数）')
        return {'ok': False, 'error': '上一轮测活还在进行中，本次跳过'}
    snapshot = copy.deepcopy(ledger)
    try:
        kept, dropped, stats = check_channels(channels, cfg, ledger, dry_run=dry_run or limit > 0)
    finally:
        release_check_lock(locked)
    dropped_n = len(dropped)
    ratio = (dropped_n / len(channels)) if channels else 0
    max_ratio = float(h.get('max_drop_ratio') or 0)
    if (not dry_run and limit <= 0 and max_ratio > 0 and len(channels) >= 10
            and ratio > max_ratio):
        # 一轮就砍掉超过 max_ratio: 现实中不可能, 大概率是本机网络/DNS 抖动
        logger.warning(f'[live_check] 本轮剔除 {dropped_n}/{len(channels)} = {ratio:.0%} '
                       f'超过 max_drop_ratio={max_ratio:.0%}，判定为本机网络异常：'
                       f'回滚台账、不改 m3u')
        if not ledger.get('degraded'):
            save_ledger(cfg, snapshot)
        return {'ok': False, 'total': len(channels), 'kept': len(kept), 'dropped': dropped_n,
                'aborted': 'mass_drop', 'ratio': round(ratio, 3),
                'error': f'单轮剔除比例 {ratio:.0%} 超过阈值 {max_ratio:.0%}，已放弃本轮结论'}
    dead_urls = {ch['url'] for ch in dropped}
    renewed = {}
    for key, entry in (ledger.get('entries') or {}).items():
        if entry.get('renewed_url'):
            renewed[entry.get('url')] = entry['renewed_url']

    result = {'ok': True, 'total': len(channels), 'kept': len(kept), 'dropped': len(dropped),
              'stats': {k: v for k, v in stats.items() if k != 'detail'}, 'dry_run': dry_run}

    if dry_run or limit > 0:
        result['detail'] = stats.get('detail') or []
        return result

    content = filter_m3u(text, dead_urls, renewed)
    _write_m3u_atomic(m3u_path, content)
    report = write_dead_report(cfg, ledger)
    if out_cfg.get('mirror_local_txt', False) and out_cfg.get('local_txt'):
        mirror = FILES_DIR / out_cfg['local_txt']
        _write_m3u_atomic(mirror, content)
    if out_cfg.get('meta'):
        meta_path = FILES_DIR / out_cfg['meta']
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            meta['last_check_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            meta['final_count'] = len(kept)
            meta['dead_total'] = len([e for e in (ledger.get('entries') or {}).values()
                                     if e.get('state') == 'dead'])
            meta['health_check'] = {k: v for k, v in stats.items() if k != 'detail'}
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:  # noqa
            logger.warning(f'[live_check] 写回 meta 失败: {e}')
    logger.info(f'[live_check] 已重写 {m3u_path}，剔除 {len(dropped)} 条，报告 {report}')
    result['report'] = str(report)
    return result


# --------------------------------------------------------------------------- #
# 定时任务入口 / CLI
# --------------------------------------------------------------------------- #
def main(task_id='live_check', *args, config_path=None, **kwargs):
    print(f'=========task_id:{task_id},args:{args},kwargs:{kwargs}=========')
    try:
        res = recheck(Path(config_path) if config_path else CONFIG_PATH)
        if not res.get('ok'):
            logger.warning(f'[live_check] {res.get("error")}')
            return f'直播线路复查跳过: {res.get("error")}'
        return (f'直播线路复查完成: 共{res["total"]}条，保留{res["kept"]}条，'
                f'剔除{res["dropped"]}条，耗时{res["stats"].get("elapsed")}s')
    except Exception as e:  # noqa
        logger.exception(f'[live_check] 任务失败: {e}')
        return f'直播线路复查失败: {e}'


def _cli():
    parser = argparse.ArgumentParser(description='直播线路体检')
    parser.add_argument('--config', default=None, help='live_sources.json 路径')
    parser.add_argument('--dry-run', action='store_true', help='只探测，不写台账、不改 m3u')
    parser.add_argument('--limit', type=int, default=0, help='只探测前 N 条')
    parser.add_argument('--recheck', action='store_true', help='复查并重写 m3u（定时任务用）')
    parser.add_argument('--stats', action='store_true', help='只打印台账统计')
    args = parser.parse_args()
    cfg_path = Path(args.config) if args.config else CONFIG_PATH
    cfg = load_config(cfg_path)

    if args.stats:
        ledger = load_ledger(cfg)
        from collections import Counter
        c = Counter(e.get('state') for e in (ledger.get('entries') or {}).values())
        print(f'台账: {ledger_path(cfg)}')
        print(f'总量 {len(ledger.get("entries") or {})} 条, 状态分布 {dict(c)}')
        print(f'更新时间 {ledger.get("updated_at")}')
        return

    if args.dry_run or args.limit:
        res = recheck(cfg_path, dry_run=True, limit=args.limit)
        if not res.get('ok'):
            print(f'失败: {res.get("error")}')
            return
        print(f'探测 {res["total"]} 条 -> 保留 {res["kept"]}，剔除 {res["dropped"]}')
        print(f'统计: {res["stats"]}')
        detail = res.get('detail') or []
        for d in detail[:40]:
            print(f'  DEAD {d["status"]:>4} {d["kind"]:<15} {d["name"]} :: {d["url"][:90]}')
        if len(detail) > 40:
            print(f'  ... 其余 {len(detail) - 40} 条略')
        print('\n(dry-run：未写台账、未修改 m3u)')
        return

    print(main(config_path=args.config))


if __name__ == '__main__':
    _cli()
