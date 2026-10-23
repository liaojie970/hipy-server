#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直播 EPG 名称归一化工具。

任务端（tasks/live_source.py）生成 EPG 索引、网页端（apps/web/views.py）查询索引时
必须使用同一套规则，否则 `CCTV-1 综合` / `CCTV1.cn@SD` / `CCTV1` 会匹配不上。
"""

import re
import unicodedata

_TVG_COUNTRY_RE = re.compile(r'\.[a-z]{2}(?:@[a-z0-9]+)?$', re.I)
_EPG_SUFFIX_RE = re.compile(
    r'(?:高清|超清|标清|蓝光|4k|8k|uhd|hd|sd|50帧|60帧|频道|直播|备用|测试|'
    r'综合|中文国际|国际|体育赛事|体育|电影|电视剧|纪录|纪录片|科教|戏曲|'
    r'社会与法|新闻|少儿|音乐|军事|农业|欧洲|美洲|赛事)$',
    re.I,
)


def norm_epg_key(value: str) -> str:
    """把频道名/tvg-id 归一成用于 EPG 匹配的 key。

    例：
        CCTV1            -> cctv1
        CCTV1.cn@SD      -> cctv1
        CCTV-1 综合       -> cctv1
        CCTV5+           -> cctv5+
        湖南卫视高清       -> 湖南卫视
    """
    s = unicodedata.normalize('NFKC', value or '').strip().lower()
    s = _TVG_COUNTRY_RE.sub('', s)
    s = re.sub(r'@.*$', '', s)
    s = re.sub(r'[\s\-_·•|/\\]+', '', s)
    s = re.sub(r'[（）()\[\]【】《》<>]+', '', s)
    # 后缀可能叠加（如“CCTV1综合高清”），循环剥到稳定为止
    while True:
        new_s = _EPG_SUFFIX_RE.sub('', s)
        if new_s == s:
            break
        s = new_s
    return s
