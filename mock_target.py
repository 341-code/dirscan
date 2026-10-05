#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mock_target.py —— 本地模拟靶场（仅用于本机自测 dirscan.py）

特点：
    1. 预置若干「存在」的目录与文件，其余路径一律 404
    2. 每个请求固定延迟 0.15 秒，模拟真实站点的网络耗时
    3. 使用 ThreadingHTTPServer，可真正并发处理请求，便于对比单线程与多线程的耗时差异

启动：
    python mock_target.py --port 8899
"""

import argparse
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG = {"delay": 0.15}

ROUTES = {
    "/": (200, 1024),
    "/index.php": (200, 2048),
    "/login.php": (200, 1536),
    "/test.php": (200, 512),
    "/phpinfo.php": (200, 4096),
    "/robots.txt": (200, 320),
    "/db.sql": (200, 8192),
    "/backup.zip": (200, 65536),
    "/admin/": (301, 0),
    "/admin/index.php": (200, 3072),
    "/admin/login.php": (200, 1280),
    "/uploads/": (301, 0),
    "/api/": (301, 0),
    "/api/v1/users": (200, 2048),
    "/config.php": (403, 256),
    "/console": (403, 256),
    "/.git/config": (403, 256),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _respond(self):
        time.sleep(CONFIG["delay"])
        path = self.path.split("?")[0]
        status, size = ROUTES.get(path, (404, 128))
        body = b"x" * size if size else b""

        self.send_response(status)
        if status == 301:
            self.send_header("Location", path + "index.php")
            body = b""
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Server", "mock-target/1.0")
        self.end_headers()
        if body:
            self.wfile.write(body)

    do_GET = _respond
    do_HEAD = _respond

    def log_message(self, fmt, *a):
        pass


def main():
    parser = argparse.ArgumentParser(description="本地模拟靶场")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--delay", type=float, default=CONFIG["delay"])
    args = parser.parse_args()

    CONFIG["delay"] = args.delay

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"模拟靶场已启动: http://127.0.0.1:{args.port}  (单请求延迟 {args.delay}s)")
    server.serve_forever()


if __name__ == "__main__":
    main()
