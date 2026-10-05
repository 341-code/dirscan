# dirscan —— 多线程目录探测脚本

安全测试中用于枚举目标站点隐藏目录与文件的自动化脚本。

## 功能特性

| 特性 | 解决的问题 |
| --- | --- |
| `requests.Session` | 复用 TCP 连接池，省去每次请求的握手开销 |
| `ThreadPoolExecutor` | 并发发起请求，把串行等待变成并行 |
| 超时控制 + 指数退避重试 | 避免线程被无响应的服务端永久卡死 |
| 令牌桶限流 | 平稳控制请求速率，避免触发目标封禁 |
| 异常兜底 + logging 落盘 | 单个任务失败不影响整体，失败可追溯 |
| 结果分流统计 + CSV 导出 | 按状态码分类输出，形成可交付的报告 |

## 快速开始

```bash
git clone https://github.com/341-code/dirscan.git
cd dirscan
pip install requests

# 本地自测（先启动模拟靶场）
python mock_target.py --port 8899 --delay 0.15
python dirscan.py --url http://127.0.0.1:8899 --wordlist wordlist.txt --workers 10

# 扫描 DVWA（本机已部署时）
python dirscan.py --url http://127.0.0.1/dvwa --wordlist wordlist.txt --workers 10 --rate 20
```

常用参数：

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--url` | 目标根地址 | 必填 |
| `--wordlist` | 词典文件 | wordlist.txt |
| `--workers` | 并发线程数（IO 密集建议 10-20） | 10 |
| `--rate` | 限流速率（请求/秒） | 50 |
| `--timeout` | 单请求超时秒数 | 5 |
| `--retries` | 失败重试次数 | 3 |
| `--ext` | 附加后缀，如 `php,html` | 空 |
| `--out` | 结果 CSV 路径 | dirscan_result.csv |

## 实测数据（本机模拟靶场，299 条词表，单请求固定延迟 0.15s）

| 运行方式 | 耗时 | 平均速率 | 命中 |
| --- | --- | --- | --- |
| 单线程（workers=1） | 45.52 秒 | 6.6 请求/秒 | 9 |
| 10 线程（workers=10，限流 1000/s） | 4.60 秒 | 65.0 请求/秒 | 9 |
| 10 线程 + 限流 30/s | 9.12 秒 | 32.8 请求/秒 | 9 |

结论：并发带来约 **9.9 倍**加速，结果与单线程完全一致；限流参数生效后速率被稳定压在设定值附近。

## 复现实测数据

### 方式一：一键复现（推荐）

```bash
python reproduce.py
```

脚本会自动启动本地模拟靶场、依次跑完三种配置、打印对照表，最后自动关闭靶场。全程只访问 `127.0.0.1`。

### 方式二：手动复现（开两个终端）

终端 A —— 启动模拟靶场，**保持运行不要关**：

```bash
python mock_target.py --port 8899 --delay 0.15
```

终端 B —— 依次执行三次扫描：

```bash
# 1. 单线程基准（耗时最长）
python dirscan.py --url http://127.0.0.1:8899 --wordlist wordlist.txt --workers 1 --rate 1000

# 2. 10 线程并发（应显著变快）
python dirscan.py --url http://127.0.0.1:8899 --wordlist wordlist.txt --workers 10 --rate 1000

# 3. 10 线程 + 限流 30/秒（速率被压住，耗时介于两者之间）
python dirscan.py --url http://127.0.0.1:8899 --wordlist wordlist.txt --workers 10 --rate 30
```

每次运行结束都会打印「总计请求 / 命中 / 失败」与「耗时 / 平均速率」。三次的命中数应当完全一致，耗时差异就是并发带来的收益。

> 复现要点：数值会随 CPU 与机器负载浮动，**量级一致**即算成功；真正要观察到的是「10 线程明显快于单线程」和「限流参数生效后速率被压下来」这两个现象。

## 一次真实的观察

词表里的 `admin` 与 `admin/` 返回结果不同——前者 404，后者 301。目录探测时必须带上结尾斜杠，否则会漏掉真实的目录。

## 目录结构

```
dirscan/
├── dirscan.py                主脚本
├── reproduce.py              一键复现实测数据
├── mock_target.py            本地模拟靶场（自测用）
├── wordlist.txt              词典（299 条）
├── examples/                 实测记录与结果样例
│   ├── run_single.txt        单线程运行记录
│   ├── run_multi.txt         10 线程运行记录
│   └── result_*.csv          扫描结果 CSV
├── LICENSE                   MIT
└── README.md
```

运行后会在当前目录生成 `dirscan.log`（日志）与 `dirscan_result.csv`（结果），两者已在 `.gitignore` 中忽略。

## 合规声明

本工具仅用于**已获得书面授权**的渗透测试与自有资产自查。未经授权对他人系统进行扫描探测，可能违反《网络安全法》《刑法》第 285 条，需承担法律责任。
