#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : github_api.py
# Author: DaShenHan&道长-----先苦后甜,任凭晚风拂柳颜------
# Date  : 2024/2/18
"""手工调试脚本: 拉一个上游仓库的 js 清单。

仓库地址写法见 utils/httpapi.py 的 parseGitRepo: `owner/repo`(github)、`gitee:owner/repo`。
用法(在 app 目录下): python t4/test/github_api.py [仓库] [目录]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import ujson

from utils.httpapi import getJSFiles, getGitContents

# 加速前缀只作用于 github; gitee 直链不需要, 留空即可
proxy = ''


def getContents(repo, path, token):
    return getGitContents(repo, path, token)


def get_js_files(repo='gitee:liaoj/dr_py', path='js', token=''):
    return getJSFiles(repo, path, token, proxy)


def write_json(js_files):
    for index, js_file in enumerate(js_files):
        js_files[index]['id'] = index + 1
        js_files[index]['status'] = 1
    with open('drpy_rules.json', mode='w+', encoding='utf-8') as f:
        f.write(ujson.dumps(js_files, ensure_ascii=False, indent=4))


if __name__ == '__main__':
    _repo = sys.argv[1] if len(sys.argv) > 1 else 'gitee:liaoj/dr_py'
    _path = sys.argv[2] if len(sys.argv) > 2 else 'js'
    js_files = get_js_files(_repo, _path)
    print(js_files[:3])
    print(f'{_repo}/{_path} 共 {len(js_files)} 个js源')
    # write_json(js_files)
