# Chuni2Api

**[中文](README.md)**

> Read and expose CHUNITHM judgment counts in real time via memory scanning.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## Overview

Scans the memory of CHUNITHM arcade rhythm game process (`chusanApp.exe`) to locate judgment count addresses, and exposes them in real time via a local HTTP server with Server-Sent Events (SSE). Only includes Justice Critical, Justice, Attack, and Miss judgment data.

### Components

| File | Description |
|------|-------------|
| [chuni2api.py](chuni2api.py) | Python version — reads game memory externally. Start anytime to begin reading. |
| [chuni2api.cpp](chuni2api.cpp) | C++ DLL version — starts with the game, relatively simpler. |
| [web.html](examples/web.html) | Simple in-game data dashboard |
| [DGLAB](/examples/DGLAB/) | DGHUB integration example. |

### Features

- **Signature-based memory scanning** — locates judgment addresses by searching for known string signatures (`NUM_jctirical\0`, etc.), not fuzzy value search. More reliable and independent of initial values.
- **Real-time SSE stream** — provides `/events` (SSE) and `/data` (JSON) endpoints on port `8888`.

---

## Usage

### Python version (chuni2api.py)

```bash
pip install psutil
python chuni2api.py
# → Web UI: http://localhost:8888
```

The script waits for `chusanApp.exe` to start, then scans for judgment data. When not in a song session, it displays `IN MENU` with all values returning `0`.

### C++ DLL version (chuni2api.cpp)

Compile with MinGW (32-bit):

```bash
g++.exe -shared -o chuni2api.asi chuni2api.cpp -lws2_32 -static -static-libgcc -static-libstdc++ -O2
```

Place `chuni2api.asi` in the game's `bin` directory with an ASI loader ([Ultimate ASI Loader](https://github.com/ThirteenAG/Ultimate-ASI-Loader) with `winmm.dll` is recommended). After launching the game, visit `http://localhost:8888` for the built-in simple web page.

### Data Dashboard (web.html)

Default connection address: `http://localhost:8888/`. You can change it in the CONFIG section at the top right of the page.

The dashboard defaults to lighting up a yellow ambient light when there are no Attack/Miss judgments and Justice Critical exceeds 100.

If there are Attacks under the above conditions, it lights up green.

When a Miss occurs, it briefly flashes red.



---

### DGHUB Integration

[About DGHUB](https://www.bilibili.com/video/BV1gM9tBFEmJ/)

Download the `DGLAB` directory and compress it (e.g., ZIP format). In the DGHUB plugin management page, select "Add Plugin" and upload the archive. Then, go to the plugin configuration page and enter the SSE endpoint address (e.g., `http://localhost:8888/events`) in the corresponding field.

You can edit the intensity function in the configuration editor.

Available variables:
```
jc=J-Critical, j=Justice, a=Attack, m=Miss
```

Example:
```
sqrt(m) * 0.1
```

A diminishing growth curve — 100 misses caps at 1.0, corresponding to 100% of the output intensity upper limit.

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/`      | GET    | Simple built-in data display page |
| `/events` | GET   | SSE stream — `data: {"critical":0,"justice":0,"attack":0,"miss":0,"status":"PLAYING"}\n\n` |
| `/data`  | GET    | Single-shot JSON snapshot (same schema) |

All endpoints include `Access-Control-Allow-Origin: *`.

---

## Disclaimer

This software reads process memory of CHUNITHM for **personal streaming and recording purposes only**. It does **not** modify game memory, inject code, or interact with the game beyond reading. Use at your own risk. This project is not affiliated with or endorsed by SEGA.
Contains AI-generated content.
