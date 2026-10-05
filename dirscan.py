#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dirscan.py —— 多线程目录探测脚本

用途：安全测试中枚举目标站点的隐藏目录 / 文件（仅限获得授权的目标）
特性：
    1. requests.Session 复用 TCP 连接，降低握手开销
    2. ThreadPoolExecutor 并发调度（IO 密集型任务，线程优于进程）
    3. 超时控制 + 指数退避重试（1s / 2s / 4s）
    4. 令牌桶限流，平稳控制请求速率，避免触发目标封禁
    5. 单个任务异常兜底 + logging 落盘，失败可追溯
    6. 结果按状态码分流统计，导出 CSV 报告

示例：
    python dirscan.py --url http://127.0.0.1:8899 --wordlist wordlist.txt --workers 10
"""

import argparse
import csv
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests

# --------------------------------------------------------------------------- #
# 令牌桶限流：桶以恒定速率补充令牌，请求必须拿到令牌才能发出
# --------------------------------------------------------------------------- #
class TokenBucket:
    def __init__(self, rate, capacity=None):
        self.rate = float(rate)                    # 每秒补充的令牌数
        self.capacity = float(capacity or rate)    # 桶容量（允许的突发量）
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                # 按流逝时间补充令牌，最多补到桶容量
                self.tokens = min(self.capacity,
                                  self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)                        # 桶空则等待下一次补充


@dataclass
class Result:
    url: str
    status: int = 0
    length: int = 0
    error: str = ""
    elapsed: float = 0.0


def build_session():
    """Session 复用连接池；连接池上限与并发数保持一致，避免频繁建连"""
    session = requests.Session()
    session.trust_env = False                        # 忽略系统代理，直连目标
    session.headers.update({"User-Agent": "dirscan/1.0 (authorized-security-test)"})
    adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def probe(session, url, bucket, timeout, retries):
    """探测单个 URL：限流 -> 请求 -> 失败则指数退避重试"""
    start = time.monotonic()
    last_error = ""
    for attempt in range(retries):
        bucket.acquire()
        try:
            resp = session.get(url, timeout=timeout, allow_redirects=False)
            return Result(url, resp.status_code, len(resp.content),
                          elapsed=time.monotonic() - start)
        except requests.RequestException as exc:
            last_error = type(exc).__name__
            if attempt < retries - 1:
                time.sleep(2 ** attempt)            # 指数退避：1s, 2s, 4s
    logging.error("请求失败 %s | %s", url, last_error)
    return Result(url, 0, 0, error=last_error, elapsed=time.monotonic() - start)


def load_wordlist(path, extensions):
    """读取词表并展开后缀；自动去重、忽略空行和注释"""
    words, seen = [], set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            word = line.strip()
            if not word or word.startswith("#"):
                continue
            candidates = [word] if "." in word.split("/")[-1] else [word] + [
                f"{word}.{ext}" for ext in extensions]
            for item in candidates:
                if item not in seen:
                    seen.add(item)
                    words.append(item)
    return words


def main():
    parser = argparse.ArgumentParser(description="多线程目录探测脚本（仅限授权目标）")
    parser.add_argument("--url", required=True, help="目标根地址，如 http://127.0.0.1:8899")
    parser.add_argument("--wordlist", default="wordlist.txt", help="词典文件路径")
    parser.add_argument("--workers", type=int, default=10, help="并发线程数（IO 密集建议 10-20）")
    parser.add_argument("--rate", type=float, default=50, help="限流速率（每秒请求数）")
    parser.add_argument("--timeout", type=float, default=5, help="超时秒数")
    parser.add_argument("--retries", type=int, default=3, help="失败重试次数")
    parser.add_argument("--ext", default="", help="额外后缀，逗号分隔，如 php,html")
    parser.add_argument("--out", default="dirscan_result.csv", help="结果 CSV 输出路径")
    parser.add_argument("--show", default="200,301,302,403", help="需要展示的状态码")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler("dirscan.log", encoding="utf-8")],
    )

    base = args.url.rstrip("/")
    extensions = [e for e in args.ext.split(",") if e]
    words = load_wordlist(args.wordlist, extensions)
    bucket = TokenBucket(args.rate, capacity=max(args.rate, 1))
    session = build_session()

    logging.info("目标 %s | 词表 %d 条 | 并发 %d | 限速 %s/s",
                 base, len(words), args.workers, args.rate)

    interesting = {int(code) for code in args.show.split(",") if code}
    found, failed, started = [], 0, time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(probe, session, f"{base}/{word}",
                               bucket, args.timeout, args.retries) for word in words]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()                # 单任务异常已在 probe 内兜底
            if result.error:
                failed += 1
            elif result.status in interesting:
                found.append(result)
                print(f"  [{result.status}] {result.url}  ({result.length} bytes)")
            if index % 50 == 0:
                logging.info("进度 %d/%d，已发现 %d", index, len(words), len(found))

    elapsed = time.monotonic() - started

    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["url", "status", "length", "elapsed_ms"])
        for item in sorted(found, key=lambda r: (r.status, r.url)):
            writer.writerow([item.url, item.status, item.length, round(item.elapsed * 1000)])

    print("\n" + "=" * 62)
    print(f"总计请求 {len(words)} 条 | 命中 {len(found)} 条 | 失败 {failed} 条")
    print(f"并发 {args.workers} 线程 | 耗时 {elapsed:.2f} 秒 | 平均 {len(words) / elapsed:.1f} 请求/秒")
    print(f"结果已写入 {args.out}，运行日志见 dirscan.log")
    print("=" * 62)


if __name__ == "__main__":
    main()
