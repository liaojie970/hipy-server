#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态文件服务器 + Vue history SPA 回退 + 反向代理到后端。

用法:
    python spa_server.py <root_dir> <port> [backend_host] [backend_port]

行为:
    1) 命中后端路径(见 PROXY_PREFIXES) -> 反向代理到后端(默认 127.0.0.1:5707)
    2) /static/ 等本地资源 -> 直接读文件
    3) 其余未知路径 -> 回退到 index.html (SPA history 模式)

这样前端只需用相对地址(/api/v1/), 换任何网络/IP 都能用。
"""
import http.client
import http.server
import os
import socketserver
import sys
import urllib.parse

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
BACKEND_HOST = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
BACKEND_PORT = int(sys.argv[4]) if len(sys.argv) > 4 else 5707

# 需要反向代理到后端的顶层路径(后端 core/server.py 的实际路由)
PROXY_PREFIXES = (
    "/api", "/media", "/files", "/config", "/epg", "/parse", "/ysp",
    "/web", "/docs", "/redoc", "/openapi.json",
    "/version", "/database_update", "/rules_refresh", "/sniffer",
    "/baidu", "/hotsugg", "/get_ip_location", "/blank", "/blog", "/doc",
)

# 前端本地资源前缀(命中则不代理, 注意 /static 后端也挂了, 必须留给前端)
LOCAL_PREFIXES = ("/static/",)

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


def is_backend_path(path):
    for p in PROXY_PREFIXES:
        if path == p or path.startswith(p + "/") or path.startswith(p + "?"):
            return True
    return False


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    # ---------------- 反向代理 ----------------
    def _proxy(self):
        conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=120)

        body = None
        cl = self.headers.get("Content-Length")
        if cl:
            try:
                body = self.rfile.read(int(cl))
            except (ValueError, OSError):
                body = None

        headers = {}
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in HOP_BY_HOP or lk == "content-length":
                continue
            headers[k] = v
        # 保留原始 Host, 让后端 request.base_url 反映前端访问地址
        headers["X-Forwarded-Proto"] = "http"
        if body is not None:
            headers["Content-Length"] = str(len(body))
        elif self.command in ("POST", "PUT", "PATCH"):
            headers["Content-Length"] = "0"

        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
        except Exception as e:  # noqa
            try:
                self.send_error(502, "Bad Gateway: %s" % e)
            except Exception:
                pass
            conn.close()
            return

        try:
            self.send_response(resp.status)
            has_len = resp.getheader("Content-Length") is not None
            for k, v in resp.getheaders():
                if k.lower() in HOP_BY_HOP:
                    continue
                self.send_header(k, v)
            if not has_len:
                data = resp.read()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)
            else:
                self.end_headers()
                if self.command != "HEAD":
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

    # ---------------- 静态 / SPA ----------------
    def _serve_static(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = self.translate_path(self.path)
        if not os.path.exists(path):
            if not parsed.path.startswith(LOCAL_PREFIXES):
                self.path = "/index.html"
        elif os.path.isdir(path) and not os.path.exists(os.path.join(path, "index.html")):
            if not parsed.path.startswith(LOCAL_PREFIXES):
                self.path = "/index.html"
        return super().do_GET() if self.command == "GET" else super().do_HEAD()

    def do_GET(self):
        if is_backend_path(urllib.parse.urlsplit(self.path).path):
            return self._proxy()
        return self._serve_static()

    def do_HEAD(self):
        if is_backend_path(urllib.parse.urlsplit(self.path).path):
            return self._proxy()
        return self._serve_static()

    def do_POST(self):
        return self._proxy()

    def do_PUT(self):
        return self._proxy()

    def do_DELETE(self):
        return self._proxy()

    def do_PATCH(self):
        return self._proxy()

    def do_OPTIONS(self):
        return self._proxy()

    def log_message(self, fmt, *args):
        pass


class ReuseTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with ReuseTCPServer(("0.0.0.0", PORT), SPAHandler) as httpd:
        print(
            "SPA server on 0.0.0.0:%d root=%s proxy->%s:%d"
            % (PORT, ROOT, BACKEND_HOST, BACKEND_PORT),
            flush=True,
        )
        httpd.serve_forever()
