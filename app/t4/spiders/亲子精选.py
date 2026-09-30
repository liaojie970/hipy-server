# coding=utf-8
# !/usr/bin/python
# File  : 亲子精选.py
# 精选内容运行时源(读写 hipy-server 的精选库, 仅展示人工审核通过的内容)
"""
这是一个 type4 的 hipy 源, 数据来自 hipy 后台【精选内容】模块。
- 只有 审核状态=通过 且 前台可见 的视频才会出现;
- 播放时用后台配置的站点 Cookie 实时解析直链;
- Cookie 存于数据库, 不落任何 web 可访问文件。
"""
import json
import math
import sys

try:
    from base.spider import BaseSpider
except ImportError:
    sys.path.append('..')
    from t4.base.spider import BaseSpider

# 播放 id 分隔符
SEP = '|'


class Spider(BaseSpider):

    def getName(self):
        return "亲子精选"

    def init(self, extend=""):
        # extend 在 t4 初始化时可能是依赖模块列表, 这里用不到
        pass

    def getDependence(self):
        return ['base_spider']

    def isVideoFormat(self, url):
        if not url:
            return False
        return any(k in str(url) for k in ['.m3u8', '.mp4', '.flv', '.mkv'])

    def manualVideoCheck(self):
        return False

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _svc():
        from apps.curated.service import curated_service
        return curated_service

    def _to_vod(self, item):
        return {
            'vod_id': str(item.get('id')),
            'vod_name': item.get('title') or '',
            'vod_pic': item.get('cover') or '',
            'vod_remarks': item.get('up_name') or '',
        }

    def _provider_name(self, code):
        try:
            for p in self._svc().list_providers():
                if p['code'] == code:
                    return p['name']
        except Exception:
            pass
        return code or '在线'

    # ------------------------------------------------------------------
    # 首页 / 分类
    # ------------------------------------------------------------------
    def homeContent(self, filter):
        classes = [{'type_id': 'all', 'type_name': '全部'}]
        try:
            for c in self._svc().get_categories():
                classes.append({'type_id': str(c['id']), 'type_name': c['name']})
        except Exception as e:
            self.log(f'[亲子精选] 获取分类失败: {e}')
        return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        try:
            items = self._svc().get_media_list()[:60]
        except Exception as e:
            self.log(f'[亲子精选] 获取首页内容失败: {e}')
            items = []
        return {'list': [self._to_vod(i) for i in items]}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        page_size = 30
        try:
            category_id = None if str(tid) in ('all', '', 'None') else int(tid)
            items = self._svc().get_media_list(category_id=category_id)
        except Exception as e:
            self.log(f'[亲子精选] 获取分类内容失败: {e}')
            items = []
        total = len(items)
        start = (pg - 1) * page_size
        page_items = items[start:start + page_size]
        return {
            'list': [self._to_vod(i) for i in page_items],
            'page': pg,
            'pagecount': math.ceil(total / page_size) if total else 0,
            'limit': page_size,
            'total': total,
        }

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------
    def detailContent(self, array):
        if not array:
            return {'list': []}
        vid = str(array[0]).split('_')[-1]
        if not vid.isdigit():
            return {'list': []}
        media = self._svc().get_media_detail(int(vid))
        if not media:
            return {'list': []}
        code = media.get('provider_code') or ''
        bvid = media.get('media_id') or ''
        episodes = media.get('episodes') or []
        play_list = []
        for idx, ep in enumerate(episodes):
            title = ep.get('title') or f'P{idx + 1}'
            play_id = SEP.join([code, bvid, str(ep.get('cid') or ''), str(media.get('id'))])
            play_list.append(f'{title}${play_id}')
        if not play_list:
            play_list.append(f"正片${SEP.join([code, bvid, '', str(media.get('id'))])}")
        return {
            'list': [{
                'vod_id': str(media.get('id')),
                'vod_name': media.get('title') or '',
                'vod_pic': media.get('cover') or '',
                'vod_content': media.get('description') or '',
                'vod_remarks': media.get('up_name') or '',
                'vod_play_from': self._provider_name(code),
                'vod_play_url': '#'.join(play_list),
            }]
        }

    # ------------------------------------------------------------------
    # 搜索(仅在已审核库内搜索)
    # ------------------------------------------------------------------
    def searchContent(self, key, quick, pg=1):
        try:
            items = self._svc().get_media_list(keyword=key, page=int(pg) if str(pg).isdigit() else 1,
                                               page_size=100)
        except Exception as e:
            self.log(f'[亲子精选] 搜索失败: {e}')
            items = []
        return {'list': [self._to_vod(i) for i in items]}

    # ------------------------------------------------------------------
    # 播放
    # ------------------------------------------------------------------
    def playerContent(self, flag, id, vipFlags):
        result = {'parse': 0, 'playUrl': '', 'jx': 0, 'url': ''}
        try:
            parts = str(id).split(SEP)
            if len(parts) < 2:
                return result
            code, bvid, cid = parts[0], parts[1], (parts[2] if len(parts) > 2 else '')
            play = self._svc().resolve_play(code, bvid, cid)
            result['url'] = play.get('url') or ''
            result['header'] = play.get('headers') or {}
        except Exception as e:
            self.log(f'[亲子精选] 解析播放失败: {e}')
        return result

    def localProxy(self, params):
        return [404, 'text/plain', f'not support: {json.dumps(params, ensure_ascii=False)}']
