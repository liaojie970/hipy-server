#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : httpapi.py
# Author: DaShenHan&道长-----先苦后甜，任凭晚风拂柳颜------
# Author's Blog: https://blog.csdn.net/qq_32394351
# Date  : 2023/12/9

import re
from network.request import Request
from t4.base.htmlParser import jsoup
import ujson
from urllib.parse import urljoin, urlparse

GIT_HOST = "api.github.com"
GIT_URL = "https://" + GIT_HOST

GITEE_HOST = "gitee.com"
GITEE_API_URL = "https://" + GITEE_HOST + "/api/v5"

# 仓库来源类型
GIT_KIND_GITHUB = 'github'
GIT_KIND_GITEE = 'gitee'

# 「参数配置」里 vod_drpy_houseN 的写法(格式: 仓库|目录, 也兼容不带目录):
#   hjdhnx/dr_py                            -> github(默认)
#   github:hjdhnx/dr_py / gh:hjdhnx/dr_py   -> github
#   gitee:liaoj/dr_py / gt:liaoj/dr_py      -> gitee
#   https://github.com/hjdhnx/dr_py.git     -> 按域名自动识别
#   https://gitee.com/liaoj/dr_py           -> 按域名自动识别(可带 /blob/main/js 之类的浏览链接尾巴)
GIT_REPO_PREFIX_RE = re.compile(r'^(gitee|gt|github|gh)[:@]', re.I)
GIT_REPO_TREE_RE = re.compile(r'/(?:tree|blob|raw)/[^/]+')
GIT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36'
# 加速前缀(如 https://ghproxy.net/) + 原始地址 组成的长链接, 用于回退直链
GIT_PROXY_PREFIX_RE = re.compile(r'^https?://[^/]+/(?=https?://)')


def parseGitRepo(repo):
    """解析仓库标识, 返回 (来源类型, owner/repo)。

    :param repo: 参数配置里的仓库值, 支持 owner/repo、gitee:owner/repo、仓库网页地址
    :return: (GIT_KIND_GITHUB | GIT_KIND_GITEE, 'owner/repo')
    """
    repo = str(repo or '').strip().strip('/')
    kind = GIT_KIND_GITHUB
    if '://' in repo:
        parsed = urlparse(repo)
        host = (parsed.hostname or '').lower()
        kind = GIT_KIND_GITEE if 'gitee' in host else GIT_KIND_GITHUB
        repo = parsed.path or ''
    else:
        matched = GIT_REPO_PREFIX_RE.match(repo)
        if matched:
            kind = GIT_KIND_GITEE if matched.group(1).lower() in ('gitee', 'gt') else GIT_KIND_GITHUB
            repo = repo[matched.end():]
    repo = repo.strip().strip('/')
    if repo.endswith('.git'):
        repo = repo[:-4]
    # 去掉网页浏览链接的尾巴: /blob/main/js/xxx.js
    repo = GIT_REPO_TREE_RE.split(repo)[0].strip('/')
    parts = [part for part in repo.split('/') if part]
    # 只保留 owner/repo, 多余的路径段丢弃(目录由配置里的 path 指定)
    return kind, '/'.join(parts[:2]) if len(parts) >= 2 else '/'.join(parts)


def stripGitProxy(url):
    """去掉加速前缀, 得到原始下载地址。"""
    return GIT_PROXY_PREFIX_RE.sub('', str(url or '').strip(), count=1)


def get_my_ip():
    my_ip = ''
    try:
        ip_check_url = 'https://httpbin.org/ip'
        request = Request(method="GET", url=ip_check_url, agent=False, follow_redirects=True, timeout=0.5)
        r = request.request()
        resp = r.json()
        return resp.get('origin') or my_ip
    except Exception as e:
        print(f'查询ip归属地发生错误:{e}')

    return my_ip


def get_location_by_ip(ipaddr):
    login_location = ''
    try:
        ip_url = f'https://qifu-api.baidubce.com/ip/geo/v1/district?ip={ipaddr}'
        request = Request(method="GET", url=ip_url, agent=False, follow_redirects=True, timeout=0.5)
        # 同步
        r = request.request()
        resp = r.json()
        if resp.get('msg') == '查询成功':
            d = resp['data']
            prov = d['prov']
            city = d['city']
            district = d['district']
            owner = d['owner']
            login_location = f'{prov}{city}{district}{owner}'
    except Exception as e:
        print(f'查询ip归属地发生错误:{e}')

    return login_location


def getHotSuggest1(url='http://4g.v.sogou.com/hotsugg', size=0):
    headers = {
        'Referer': 'https://gitcode.net/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36',
    }
    jsp = jsoup(url)
    pdfh = jsp.pdfh
    pdfa = jsp.pdfa
    pd = jsp.pd
    try:
        request = Request(method="GET", url=url, headers=headers, agent=False, follow_redirects=True, timeout=2)
        r = request.request()
        html = r.text
        data = pdfa(html, 'ul.hot-list&&li')
        suggs = [{'title': pdfh(dt, 'a&&Text'), 'url': pd(dt, 'a&&href')} for dt in data]
        return suggs
    except:
        return []


def getHotSuggest2(url='https://pbaccess.video.qq.com/trpc.videosearch.hot_rank.HotRankServantHttp/HotRankHttp',
                   size=0):
    size = int(size) if size else 50
    pdata = ujson.dumps({"pageNum": 0, "pageSize": size})
    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36',
        'content-type': 'application/json'}
    try:
        request = Request(method="POST", url=url, data=pdata, headers=headers, agent=False, follow_redirects=True,
                          timeout=2)
        r = request.request()
        html = r.json()
        data = html['data']['navItemList'][0]['hotRankResult']['rankItemList']
        suggs = [{'title': dt['title'], 'url': dt['url']} for dt in data]
        return suggs
    except:
        return []


def getHotSuggest(s_from, size):
    if s_from == 'sougou':
        return getHotSuggest1(size=size)
    else:
        return getHotSuggest2(size=size)


def getYspContent(ysp_url):
    headers = {
        'Referer': 'https://www.yangshipin.cn/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    }
    request = Request(method="get", url=ysp_url, headers=headers, agent=False, follow_redirects=True, timeout=5)
    r = request.request()
    html = r.text
    m3u8_list = html.split('\n')
    new_m3u8_list = []
    for m3u8_str in m3u8_list:
        if (not m3u8_str.startswith('#')) and m3u8_str.endswith('.ts'):
            new_m3u8_list.append(urljoin(ysp_url, m3u8_str))
        else:
            new_m3u8_list.append(m3u8_str)
    m3u8_text = '\n'.join(new_m3u8_list)
    return m3u8_text


def _getGithubContents(repo, path, token):
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Connection": "keep-alive",
        "Host": GIT_HOST,
        "User-Agent": GIT_UA,
    }
    guest_token = token or ""
    if guest_token:
        # headers["Authorization"] = "token " + guest_token
        headers["Authorization"] = "Bearer " + guest_token
    request = Request(method="get", url=GIT_URL + "/repos/" + repo + "/contents/" + (path or ""),
                      headers=headers, agent=False, follow_redirects=True,
                      timeout=10)
    r = request.request()
    res = r.json()
    return res


def _getGiteeContents(repo, path, token=''):
    """gitee 仓库目录列表(api/v5), 返回结构跟 github 基本一致。

    注意: 「参数配置」里的 vod_git_token 是 github 令牌, 传给 gitee 会 401, 所以这里不传。
    公开仓库无需令牌, 如遇 gitee 限流可稍后再试。
    """
    headers = {
        "Accept": "application/json",
        "Connection": "keep-alive",
        "User-Agent": GIT_UA,
    }
    url = GITEE_API_URL + "/repos/" + repo + "/contents/" + (path or "")
    request = Request(method="get", url=url, headers=headers, agent=False,
                      follow_redirects=True, timeout=10)
    r = request.request()
    try:
        res = r.json()
    except Exception:
        raise RuntimeError(f'gitee接口返回了无法解析的内容, HTTP {r.status_code}: {str(r.text)[:200]}')
    return res


def getGitContents(repo, path, token):
    """获取仓库目录内容。repo 支持 github / gitee 两种来源(见上面的格式说明)。"""
    kind, repo_path = parseGitRepo(repo)
    if not repo_path or '/' not in repo_path:
        raise RuntimeError(f'仓库地址不合法:{repo}, 正确格式如 hjdhnx/dr_py 或 gitee:liaoj/dr_py')
    path = str(path or '').strip().strip('/')
    if kind == GIT_KIND_GITEE:
        return _getGiteeContents(repo_path, path, token)
    return _getGithubContents(repo_path, path, token)


def _giteeDownloadUrl(item, repo, path):
    """gitee 文件直链, 优先用接口给的 download_url, 没有就从 html_url 推出来。"""
    download_url = str(item.get('download_url') or '').strip()
    if not download_url:
        html_url = str(item.get('html_url') or '').strip()
        download_url = html_url.replace('/blob/', '/raw/') if '/blob/' in html_url else ''
    if not download_url:
        prefix = f'{path}/' if path else ''
        download_url = f'https://{GITEE_HOST}/{repo}/raw/main/{prefix}{item.get("name", "")}'
    return download_url


def getJSFiles(repo, path, token, proxy):
    """列出仓库目录里的 js 文件。

    url: 用于「导入源」下载的地址。github 会拼上加速前缀(proxy, 可为空=直连);
         gitee 直接用仓库直链, 不需要(也不该)拼 github 的加速前缀。
    raw_url: 不带加速前缀的原始地址, 导入失败时可用于回退。
    """
    kind, repo_path = parseGitRepo(repo)
    path = str(path or '').strip().strip('/')
    files = getGitContents(repo, path, token)
    if isinstance(files, dict):
        raise RuntimeError(f'获取 {kind} 仓库 {repo_path}/{path} 失败:{files.get("message") or files}')
    if not isinstance(files, list):
        raise RuntimeError(f'获取 {kind} 仓库 {repo_path}/{path} 失败:{files}')
    proxy = str(proxy or '').strip()
    js_files = []
    for file in files:
        if not (str(file.get('name') or '').endswith('.js') and file.get('type') == 'file'):
            continue
        if kind == GIT_KIND_GITEE:
            # gitee 直接用自己的 raw 直链, 不拼 github 的加速前缀
            raw_url = _giteeDownloadUrl(file, repo_path, path)
            url = raw_url
        else:
            raw_url = str(file.get('download_url') or '')
            # 直链本身带 http(s) 时才拼加速前缀, 避免拼出畸形地址
            url = proxy + raw_url if (proxy and raw_url.startswith('http')) else raw_url
        js_files.append({
            "rule": re.sub(r'\.js$', '', file['name']),
            "name": file['name'],
            "size": f"{round((file.get('size') or 0) / 1024, 2)}kb",
            "url": url,
            "raw_url": raw_url,
        })
    return js_files
