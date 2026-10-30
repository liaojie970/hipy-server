#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : qjs_drpy.py
# Author: DaShenHan&道长-----先苦后甜，任凭晚风拂柳颜------
# Date  : 2024/3/20

import os
import threading
import ujson
from quickjs import Context
from utils.quickjs_ctx import initContext
from utils.tools import get_md5
from t4.test.ad_remove import fixAdM3u8
from concurrent.futures import ThreadPoolExecutor, wait


class Drpy:
    def __init__(self, api='drpy', t4_js_api='', debug=0):
        """
        初始化一个drpy类
        @param api: 可以传api如996影视.js
        @param t4_js_api: 本地代理url
        @param debug: 开启调试模式|默认关闭，开启后可以显示源里打印的日志
        """
        key = '_' + get_md5(api)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()
        self._api = api
        self.key = key
        self.t4_js_api = t4_js_api
        self.debug = debug
        self.ctx = self.submit(self.initCtx)

    def close(self, delay=60):
        """
        释放线程池与 JS 运行时。

        背景: Drpy 每个实例自带一个常驻线程 (ThreadPoolExecutor max_workers=1)
        和一个 quickjs Context。旧版本从不回收，源被重新初始化(TTL 到期/JS 变更)
        就会泄漏一条线程 + 一块 JS 堆，进程 RSS 会持续上涨直到被系统杀掉。

        @param delay: 延迟多少秒真正关闭。留出宽限期，避免同一请求里
                      已取到旧实例的并发调用被立即打断。
        """
        ex = getattr(self, 'executor', None)
        if ex is None:
            return

        def _do():
            try:
                self.executor = None
                ex.shutdown(wait=False)
            except Exception:  # noqa
                pass
            try:
                self.ctx = None
            except Exception:  # noqa
                pass

        if delay and delay > 0:
            t = threading.Timer(delay, _do)
            t.daemon = True
            t.start()
        else:
            _do()

    def __del__(self):
        try:
            self.close(delay=0)
        except Exception:  # noqa
            pass

    def initCtx(self) -> Context:
        base_path = os.path.dirname(__file__)

        def _(p):
            return os.path.join(base_path, p)

        def _get_prefix_code():
            """
            drpy2.js的注入前置文本
            @return:
            """
            return """
            cheerio.jinja2 = function (template, obj) {
                return jinja.render(template, obj);
            };
            """.strip() + '\n'

        with open(_('qjs_module_muban.js'), encoding='utf-8') as f:
            _qjs_module_muban = f.read()
        with open(_('qjs_module_cheerio.js'), encoding='utf-8') as f:
            _qjs_module_cheerio = f.read()
        with open(_('qjs_module_jinja2.js'), encoding='utf-8') as f:
            _qjs_module_jinja2 = f.read()
        with open(_('qjs_module_json5.js'), encoding='utf-8') as f:
            _qjs_module_json5 = f.read()
        with open(_('qjs_module_gbk.js'), encoding='utf-8') as f:
            _qjs_module_gbk = f.read()
        with open(_('qjs_module_crypto.js'), encoding='utf-8') as f:
            _qjs_module_crypto = f.read()
        with open(_('qjs_module_jsencrypt.js'), encoding='utf-8') as f:
            _qjs_module_jsencrypt = f.read()
        with open(_('qjs_module_nodersa.js'), encoding='utf-8') as f:
            _qjs_module_nodersa = f.read()
        with open(_('qjs_module_pako.js'), encoding='utf-8') as f:
            _qjs_module_pako = f.read()
        with open(_('qjs_module_drpy2.js'), encoding='utf-8') as f:
            _qjs_module_drpy2 = _get_prefix_code() + f.read() + f'\nglobalThis.{self.key} = ' + """
            { getRule,runMain, init, home, homeVod, category, detail,play, search, proxy, sniffer, isVideo, fixAdM3u8Ai };
            """

        ctx = initContext(Context(), url='', prefix_code='true', env={'debug': self.debug}, getParams=lambda: {},
                          getCryptoJS=lambda: 'true')
        ctx.add_callable('getProxy', lambda is_public: self.getProxyUrl(is_public))
        ctx.module(_qjs_module_muban)
        ctx.module(_qjs_module_cheerio)
        ctx.module(_qjs_module_jinja2)
        ctx.module(_qjs_module_json5)
        ctx.module(_qjs_module_gbk)
        ctx.module(_qjs_module_crypto)
        ctx.module(_qjs_module_jsencrypt)
        ctx.module(_qjs_module_nodersa)
        ctx.module(_qjs_module_pako)
        ctx.module(_qjs_module_drpy2)
        return ctx

    def submit(self, function, *args):
        ex = self.executor
        if ex is None:
            raise RuntimeError(f'源实例已释放: {self._api}')
        with self._lock:
            future = ex.submit(function, *args)
            wait([future])
            return future.result()

    def setDebug(self, debug):
        return self.submit(self.ctx.set, '_debug', debug)

    def getName(self):
        return self._api.split('/')[-1]

    def toJsObJect(self, any):
        if isinstance(any, dict) or isinstance(any, list):
            return self.submit(self.ctx.parse_json, ujson.dumps(any, ensure_ascii=False))
        return any

    @staticmethod
    def toDict(_object):
        if isinstance(_object, (type(None), str, bool, float, int)):
            return _object
        return ujson.loads(_object.json())

    @staticmethod
    def setDict(_str):
        return ujson.loads(_str)

    def call(self, func: str, *args):
        return self.submit(self._call, func, *args)

    def _call(self, func: str, *args, run_gc=True):
        def convert_arg(arg):
            if isinstance(arg, (type(None), str, bool, float, int)):
                return arg
            else:
                # More complex objects are passed through JSON.
                return self.ctx.parse_json(ujson.dumps(arg, ensure_ascii=False))

        try:
            return self.ctx.eval(f'globalThis.{self.key}.{func}')(*[convert_arg(a) for a in args])
        finally:
            if run_gc:
                self.ctx.gc()

    def init(self, extend=""):
        self.call('init', extend)

    def getRule(self, key=None):
        return self.toDict(self.call('getRule', key))

    def homeContent(self, filter=None, home_html=None, class_parse=None):
        return self.setDict(self.call('home', filter, home_html, class_parse))

    def homeVideoContent(self):
        return self.setDict(self.call('homeVod'))

    def categoryContent(self, tid, pg, filterable, extend):
        return self.setDict(self.call('category', tid, pg, filterable, extend))

    def detailContent(self, ids):
        if isinstance(ids, list):
            ids = ids[0]
        return self.setDict(self.call('detail', ids))

    def searchContent(self, key, quick, pg=1):
        return self.setDict(self.call('search', key, quick, pg))

    def playerContent(self, flag, id, vipFlags=None):
        return self.setDict(self.call('play', flag, id, vipFlags))

    def localProxy(self, params):
        return self.toDict(self.call('proxy', params))

    def getProxyUrl(self, is_public=True):
        """
        获取本地代理地址
        @param is_public: 是否外网
        @return:
        """
        proxy_url = f'http://127.0.0.1:5707/api/v1/vod/{self._api}?pwd=dzyyds&proxy=true&do=js' if is_public else ''
        return self.t4_js_api or proxy_url

    def isVideo(self):
        """
        返回是否为视频的匹配字符串
        @return: None空 reg:正则表达式  js:input js代码
        """
        # rule = self.toDict(self.submit(self.ctx.eval, f'globalThis.{self.key}.getRule()'))
        # rule = self.toDict(self.call('getRule'))
        # is_video_str = str(rule.get('is_video') or '')

        is_video_str = self.call('getRule', 'is_video')
        # print('is_video_str:', is_video_str)
        if is_video_str and not is_video_str.startswith('reg:'):
            is_video_str = 'reg:' + is_video_str
        return is_video_str
        # return 'js:input.includes(".m3u8)?true:false'

    @staticmethod
    def adRemove():
        """
        m3u8广告移除函数。将自动执行返回的字符串的本地代理功能
        @return: None空 reg:正则表达式  js:input js代码
        """
        # return 'reg:/video/adjump.*?ts'

    @staticmethod
    def fixAdM3u8(*args):
        return fixAdM3u8(*args)


if __name__ == '__main__':
    drpy = Drpy(debug=1)
    with open('../files/drpy_js/农民影视新.js', encoding='utf-8') as f:
        code = f.read()
    drpy.init(code)
    drpy.setDebug(1)
    print(drpy.homeContent())
    print(drpy.homeVideoContent())
    print(drpy.categoryContent('2', 1, False, {}))
    print(drpy.searchContent("斗罗大陆", False, 1))
    print(drpy.detailContent('https://m.emsdn.cn/vod-detail-id-38818.html'))
    # f = quickjs.Function(
    #     "adder", """
    #             function adder(x, y) {
    #                 return x + y;
    #             }
    #             """)
    print(drpy.playerContent("线路①", "https://m.emsdn.cn/vod-play-id-38818-src-1-num-1.html", []))
