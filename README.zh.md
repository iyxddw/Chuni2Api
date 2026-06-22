# Chuni2Api

> 通过内存扫描实时读取并暴露中二节奏（CHUNITHM）的判定计数。

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 概述

通过扫描中二节奏（CHUNITHM）街机音游进程（`chusanApp.exe`）的内存定位判定计数地址，并通过本地 HTTP 服务器以 SSE（Server-Sent Events）协议实时输出。

### 组件

| 文件 | 说明 |
|------|------|
| [chuni2api.py](chuni2api.py) | Python 版 — 从外部读取游戏内存。随时启动开始读取 |
| [chuni2api.cpp](chuni2api.cpp) | C++ 版 — 随游戏启动，相对简单一点 |
| [web.py](web.py) | 测试前端对接页面 |

### 功能特性

- **基于签名的内存扫描** — 通过搜索已知字符串签名（`NUM_jctirical\0` 等）定位判定地址，而非模糊数值搜索。更稳定，不依赖初始值。
- **实时 SSE 流** — 在 `8888` 端口提供 `/events`（SSE 流）和 `/data`（JSON）端点。
---

## 使用方法

### Python 版（chuni2api.py）

```bash
pip install psutil
python chuni2api.py
# → 网页 UI: http://localhost:8888
```

脚本会等待 `chusanApp.exe` 启动，然后扫描判定数据。不在打歌途中显示IN MENU，返回值均为0

### C++ DLL 版（chuni2api.cpp）

使用 MinGW 编译（32 位）：

```bash
g++.exe -shared -o chuni2api.asi chuni2api.cpp -lws2_32 -static -static-libgcc -static-libstdc++ -O2
```

将 `chuni2api.asi` 放入游戏的 `bin` 目录，并配合 ASI 加载器使用（推荐使用 [Ultimate ASI Loader](https://github.com/ThirteenAG/Ultimate-ASI-Loader) 提供的 `winmm.dll`）。启动游戏后，访问 `http://localhost:8888` 提供了一个内建的简易网页。

### 测试前端对接页面（web.py）

```bash
# 第一步：启动后端（Python 或 C++ 版）
python chuni2api.py

# 第二步：另开一个终端，启动代理
python web.py
# → 访问: http://localhost:8889
```

`web.py` 无额外依赖，仅使用 Python 标准库。

---



## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/`      | GET | 简易内建数据展示页面 |
| `/events` | GET | SSE 流 — `data: {"critical":0,"justice":0,"attack":0,"miss":0,"status":"PLAYING"}\n\n` |
| `/data`  | GET | 一次性 JSON 快照（同 schema） |

所有端点均包含 `Access-Control-Allow-Origin: *`。


## 免责声明

本软件仅用于读取 CHUNITHM 进程内存，**仅供个人直播和录屏使用**。它**不会**修改游戏内存、注入代码或以任何超出读取的方式与游戏交互。使用风险自负。本项目与 SEGA 无关，亦未获 SEGA 认可。
包含AI生成内容