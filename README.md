# Chuni2Api

> Read and expose CHUNITHM judgment counts in real time via memory scanning.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**[中文版](README.zh.md)**

---

## Overview

Scans the memory of CHUNITHM arcade rhythm game process (`chusanApp.exe`) to locate judgment count addresses, and exposes them in real time via a local HTTP server with Server-Sent Events (SSE).Only includes Justice Critical, Justice, Attack, and Miss judgment data.

### Components

| File | Description |
|------|-------------|
| [chuni2api.py](chuni2api.py) | Python version — reads game memory externally. Start anytime to begin reading. |
| [chuni2api.cpp](chuni2api.cpp) | C++ version — starts with the game, relatively simpler. |
| [web.py](web.py) | Test frontend integration page. |

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

### Test frontend page (web.py)

```bash
# Step 1: Start the backend (Python or C++ version)
python chuni2api.py

# Step 2: In another terminal, start the proxy
python web.py
# → Visit: http://localhost:8889
```

`web.py` has zero external dependencies — standard library only.

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
