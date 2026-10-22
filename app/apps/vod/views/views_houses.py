#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : views_houses.py
# Author: DaShenHan&道长-----先苦后甜，任凭晚风拂柳颜------
# Date  : 2024/2/19

from typing import Any, Optional, List

import requests
import ujson
from core.logger import logger
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload
from time import time
from utils.vod_tool import get_interval
from common import deps, error_code
from common.resp import respSuccessJson, respErrorJson
from ..curd.curd_configs import curd_vod_configs as curd
import os
import io
from pathlib import Path
from core.constants import BASE_DIR
from utils.httpapi import getGitContents, getJSFiles, stripGitProxy
from apps.permission.models import Users
from utils.web import getRealHost

router = APIRouter()

access_name = 'vod:houses'
api_url = '/houses'


def read_records():
    # 用项目根目录(app/)定位文件, 避免从其他工作目录启动服务时读不到仓库数据(列表空白)
    project_dir = BASE_DIR
    file_path = os.path.join(project_dir, 't4/files/json/drpy_rules.json')
    file_path = Path(file_path).as_posix()
    drpy_dir = os.path.join(project_dir, 't4/files/drpy_js/')
    try:
        with open(file_path, encoding='utf-8') as f:
            records = ujson.loads(f.read())

        for record in records:
            local_file = os.path.join(drpy_dir, record['name'])
            if os.path.exists(local_file):
                record['status'] = 1
            else:
                record['status'] = 0

    except Exception as e:
        logger.warning(f'读取本地drpy仓库源文件:{file_path} 发送了错误:{e}')
        records = []
    return records


def fetch_js_content(record, timeout=20):
    """下载仓库列表里某个源的 js 内容。

    依次尝试: 列表里的 url(可能带加速前缀) -> raw_url(直链) -> 去掉加速前缀后的直链。
    这样即使参数配置里的 git 加速代理过期/被墙, 只要原始地址可达仍能导入。
    """
    url = str(record.get('url') or '').strip()
    candidates = [url, str(record.get('raw_url') or '').strip(), stripGitProxy(url)]
    tried = []
    for candidate in candidates:
        if not candidate or candidate in tried:
            continue
        tried.append(candidate)
        try:
            r = requests.get(candidate, timeout=timeout,
                             headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            if r.status_code == 200 and r.content:
                return r.content
            logger.warning(f'下载源{record.get("name")}失败:{candidate} -> HTTP {r.status_code}')
        except Exception as e:
            logger.warning(f'下载源{record.get("name")}异常:{candidate} -> {e}')
    raise RuntimeError(f'没有可用地址, 已尝试: {tried}')


@router.get(api_url + '/list', summary="查询仓库源列表")
async def searchRecords(*,
                        u: Users = Depends(deps.user_perm([f"{access_name}:get"])),
                        page: int = 1,
                        page_size: int = 20,
                        rule: str = "",
                        status: int = None
                        ):
    records = read_records()
    if records:
        if rule:
            records = [record for record in records if rule in record['rule']]
        if status is not None:
            records = [record for record in records if status == record['status']]

    total = len(records)
    start = page_size * (page - 1)
    end = page_size * page
    res = {
        'data': records[start:end], 'total': total
    }

    return respSuccessJson(res)


@router.put(api_url + '/{_ids}', summary="通过ID导入源")
def addRecordByID(*,
                  db: Session = Depends(deps.get_db),
                  request: Request,
                  u: Users = Depends(deps.user_perm([f"{access_name}:delete"])),
                  _ids: str
                  ):
    host = str(request.base_url).rstrip('/')
    host = getRealHost(host, request)
    headers = dict(request.headers)
    logger.info(f'user:{u}')
    _ids = list(map(lambda x: int(x), _ids.split(',')))
    t1 = time()
    records = read_records()
    records = [record for record in records if record['id'] in _ids]
    success = []
    failed = []
    for record in records:
        name = record['name']
        try:
            content = fetch_js_content(record)
            file = io.BytesIO(content)
            files = {"files": (name, file)}
            params = {
                "updateSupport": True,
                "group": 't4/files/drpy_js',
            }
            r = requests.post(f'{host}/api/v1/vods/rules/file/uploadData', files=files, params=params, headers=headers)
            resp = r.json()
            if resp.get('code') == 0:
                success.append(record)
            else:
                failed.append(name)
        except Exception as e:
            failed.append(name)
            logger.info(f'导入源{name}发生了错误:{e}')

    cost = get_interval(t1)
    if failed and not success:
        return respErrorJson(error=error_code.ERROR_INTERNAL.set_msg(
            f'导入失败, 请到「参数配置」检查上游仓库地址/git加速代理, 或在「上游仓库」重新获取仓库数据: {",".join(failed[:5])}'))
    return respSuccessJson(data=f'导入成功{len(success)}/{len(records)}个源,耗时{cost}ms')


@router.post(api_url + "/refresh", summary="刷新配置")
def refreshRecords(*,
                   db: Session = Depends(deps.get_db),
                   u: Users = Depends(deps.user_perm([f"{access_name}:post"])), ):
    token = curd.getByKey(db, key='vod_git_token').get('value') or ''
    proxy = curd.getByKey(db, key='vod_git_proxy').get('value') or ''
    token = token.strip()
    proxy = proxy.strip()

    logger.info(f'token:{token},proxy:{proxy}')
    houses = curd.getHouses(db)
    houses = [h for h in houses if '|' in h['value']]
    records = []

    project_dir = BASE_DIR
    file_path = os.path.join(project_dir, 't4/files/json/drpy_rules.json')
    file_path = Path(file_path).as_posix()

    _id = 1
    errors = []
    for house in houses:
        name = house['name']
        repo = house['value'].split('|')[0]
        path = house['value'].split('|')[1]
        try:
            js_files = getJSFiles(repo, path, token, proxy)
        except Exception as e:
            # 单个仓库失败不影响其他仓库, 但至少得有一个成功才覆盖本地清单
            logger.warning(f'获取上游仓库{name}({repo}|{path})失败:{e}')
            errors.append(f'{name}({repo}|{path}): {e}')
            continue
        for js_file in js_files:
            js_file['id'] = _id
            js_file['from'] = name

            records.append(js_file)
            _id += 1

    if not records:
        return respErrorJson(error=error_code.ERROR_INTERNAL.set_msg(
            '全部仓库获取失败, 请到「参数配置」检查仓库地址(github 写 owner/repo, gitee 写 gitee:owner/repo)、'
            f'git令牌和加速代理: {"; ".join(errors) or "未配置仓库"}'))

    with open(file_path, mode='w+', encoding='utf-8') as f:
        f.write(ujson.dumps(records, ensure_ascii=False, indent=4))
    msg = '刷新成功'
    if errors:
        msg = f'刷新完成, {len(errors)}/{len(houses)}个仓库获取失败: {"; ".join(errors[:3])}'
    return respSuccessJson(data={}, msg=msg)
