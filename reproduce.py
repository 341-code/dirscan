#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reproduce.py —— 一键复现 README 中的实测数据

它会自动完成：
    1. 在后台启动本地模拟靶场（单请求固定延迟 0.15s）
    2. 用三种配置依次扫描同一份词表（299 条）
    3. 打印对照表，并与 README 的参考值比较
    4. 结束后自动关闭靶场

用法：
    python reproduce.py

注意：整个过程只访问本机回环地址 127.0.0.1，不涉及任何外部目标。
"""

import os
import re
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8899
DELAY = 0.15

# (场景名, 附加参数, README 参考耗时)
SCENARIOS = [
    ("单线程",           ["--workers", "1",  "--rate", "1000"], 45.52),
    ("10 线程",          ["--workers", "10", "--rate", "1000"], 4.60),
    ("10 线程 + 限流 30", ["--workers", "10", "--rate", "30"],   9.12),
]


def display_width(text):
    """按终端显示宽度计算（中文占 2 列）"""
    return sum(2 if ord(ch) > 127 else 1 for ch in text)


def pad(text, width):
    return text + " " * max(0, width - display_width(text))


def main():
    try:
        import requests  # noqa: F401
    except ImportError:
        print("缺少依赖：requests")
        print("请先执行：pip install requests")
        return 1

    try:
        import mock_target
    except ImportError:
        print("找不到 mock_target.py，请确认在 dirscan 目录下运行本脚本。")
        return 1

    mock_target.CONFIG["delay"] = DELAY
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), mock_target.Handler)
    except OSError:
        print(f"端口 {PORT} 已被占用，请先关闭占用该端口的进程，或修改脚本开头的 PORT。")
        return 1

    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"模拟靶场已启动：http://127.0.0.1:{PORT}（单请求延迟 {DELAY}s）")
    print(f"词表：wordlist.txt    场景数：{len(SCENARIOS)}\n")

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    rows = []
    try:
        for index, (name, extra, reference) in enumerate(SCENARIOS, start=1):
            cmd = [
                sys.executable, str(HERE / "dirscan.py"),
                "--url", f"http://127.0.0.1:{PORT}",
                "--wordlist", str(HERE / "wordlist.txt"),
                "--out", str(HERE / "reproduce_result.csv"),
            ] + extra

            print(f"[{index}/{len(SCENARIOS)}] {name} 运行中 ...", flush=True)
            wall = time.monotonic()
            proc = subprocess.run(cmd, cwd=str(HERE), env=env,
                                  capture_output=True, text=True, encoding="utf-8")
            wall = time.monotonic() - wall
            out = (proc.stdout or "") + (proc.stderr or "")

            total = re.search(r"总计请求 (\d+) 条", out)
            hits = re.search(r"命中 (\d+) 条", out)
            failed = re.search(r"失败 (\d+) 条", out)
            elapsed = re.search(r"耗时 ([\d.]+) 秒", out)
            rate = re.search(r"平均 ([\d.]+) 请求/秒", out)

            if not (hits and elapsed and total and failed and rate):
                print("    该场景运行失败，原始输出：")
                print(out[-800:])
                return 1

            rows.append({
                "name": name,
                "total": total.group(1),
                "hits": hits.group(1),
                "failed": failed.group(1),
                "elapsed": float(elapsed.group(1)),
                "rate": rate.group(1),
                "wall": wall,
                "reference": reference,
            })
            print(f"    完成：耗时 {float(elapsed.group(1)):.2f}s，"
                  f"命中 {hits.group(1)} 条，失败 {failed.group(1)} 条")
    finally:
        server.shutdown()

    print("\n" + "=" * 68)
    print(pad("场景", 22) + pad("耗时(秒)", 12) + pad("速率(请求/秒)", 16)
          + pad("命中", 8) + "失败")
    print("-" * 68)
    for row in rows:
        print(pad(row["name"], 22) + pad(f"{row['elapsed']:.2f}", 12)
              + pad(row["rate"], 16) + pad(row["hits"], 8) + row["failed"])
    print("=" * 68)

    single = rows[0]["elapsed"]
    multi = rows[1]["elapsed"]
    hit_set = {row["hits"] for row in rows}
    print(f"\n加速比：{single:.2f}s ÷ {multi:.2f}s ≈ {single / multi:.1f} 倍")
    print(f"三次命中的目录数是否一致：{'是' if len(hit_set) == 1 else '否'}")
    print("README 参考值：" + "，".join(f"{n} {v}s" for n, _, v in SCENARIOS))
    print("（本机 CPU 与负载不同会导致数值浮动，量级一致即视为复现成功）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
