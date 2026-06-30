"""DGHub 插件 — CHUNITHM 判定数据 → 外部硬件联动。

连接 Chuni2Api 的 /events SSE 端点，实时读取四种判定计数。
每当 MISS 增加时触发外部硬件，支持两种模式：
  - 固定模式: 每次 MISS 输出固定强度
  - 函数模式: 用户自定义公式，用 jc/j/a/m 变量计算强度

依赖: pip install websockets
"""

import asyncio
import json
import math
import os
import socket
import sys
import threading
import urllib.request
import urllib.error

try:
    import websockets
except ImportError:
    print("缺少 websockets，请: pip install websockets", file=sys.stderr)
    raise


async def main() -> None:
    host = os.environ["DGHUB_HOST"]
    port = os.environ["DGHUB_PORT"]
    token = os.environ["DGHUB_TOKEN"]

    # ── 用户可配置项（由 DGHub 推送） ──
    cfg = {
        "endpoint": "http://localhost:8888/events",
        "debug": False,
        "mode": "fixed",
        "fixed_strength": 30,
        "formula": "min(m * 0.05, 1)",
        "duration_s": 1.5,
        "channel": "both",
    }

    # 函数模式可用的数学函数
    MATH_FUNCS = {
        "sqrt": math.sqrt,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "asin": math.asin, "acos": math.acos, "atan": math.atan,
        "log": math.log, "log2": math.log2, "log10": math.log10,
        "exp": math.exp, "pow": math.pow,
        "abs": abs, "round": round, "min": min, "max": max,
        "pi": math.pi, "e": math.e,
    }

    def calc_strength(jc: int, j: int, a: int, m: int) -> int:
        """根据当前模式和判定数据计算强度百分比"""
        if cfg["mode"] == "fixed":
            return int(cfg["fixed_strength"])
        else:
            try:
                ns = {"jc": jc, "j": j, "a": a, "m": m, **MATH_FUNCS}
                y = eval(cfg["formula"], {"__builtins__": {}}, ns)
                # 公式输出 0~1 比值，内部 ×100 转为百分比
                return max(0, min(100, int(y * 100)))
            except Exception:
                return 0

    loop = asyncio.get_running_loop()
    sse_queue: asyncio.Queue = asyncio.Queue()

    # ── SSE 后台读取线程 ──
    sse_stop = threading.Event()
    sse_lock = threading.Lock()
    sse_thread = [None]  # mutable box: [Thread | None]
    sse_resp = [None]    # mutable box: [HTTPResponse | None]

    def sse_read(endpoint: str) -> None:
        """阻塞读 SSE 流 → 入队 asyncio（在后台线程运行）"""
        try:
            req = urllib.request.Request(endpoint)
            req.add_header("Accept", "text/event-stream")
            req.add_header("Cache-Control", "no-cache")
            resp = urllib.request.urlopen(req, timeout=10)
            # 禁用 Nagle + 减小缓冲区，降低延迟
            sock = resp.fp.raw._sock if hasattr(resp.fp, "raw") else None
            if sock:
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception:
                    pass
            with sse_lock:
                sse_resp[0] = resp
            buf = b""
            # 优先用 read1 读取所有可用的数据（一次 read 系统调用）
            reader = resp.fp.read1 if hasattr(resp.fp, "read1") else lambda n: resp.read(n)
            while not sse_stop.is_set():
                try:
                    chunk = reader(64)
                except Exception:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n\n" in buf:
                    raw, buf = buf.split(b"\n\n", 1)
                    for line in raw.split(b"\n"):
                        if line.startswith(b"data: "):
                            payload = line[6:].decode("utf-8", errors="replace")
                            try:
                                obj = json.loads(payload)
                                loop.call_soon_threadsafe(sse_queue.put_nowait, obj)
                            except json.JSONDecodeError:
                                pass
            # 如果不是主动停止 → 连接意外断开，通知主循环重连
            if not sse_stop.is_set():
                loop.call_soon_threadsafe(
                    sse_queue.put_nowait, {"_error": "连接意外断开"}
                )
        except Exception as exc:
            loop.call_soon_threadsafe(
                sse_queue.put_nowait, {"_error": str(exc)}
            )
        finally:
            with sse_lock:
                sse_resp[0] = None

    def sse_start(endpoint: str) -> None:
        sse_stop.clear()
        t = threading.Thread(target=sse_read, args=(endpoint,), daemon=True)
        sse_thread[0] = t
        t.start()

    def sse_stopper() -> None:
        sse_stop.set()
        with sse_lock:
            r = sse_resp[0]
            if r is not None:
                try:
                    r.close()
                except Exception:
                    pass
                sse_resp[0] = None
        t = sse_thread[0]
        if t is not None and t.is_alive():
            t.join(timeout=3)

    # ── SSE 状态追踪（独立协程消费队列） ──
    state = {
        "last_miss": 0,
        "last_status": "",
        "last_debug": {"miss": 0, "critical": 0, "justice": 0, "attack": 0},
        "first_event": True,
    }

    async def sse_processor(ws) -> None:
        """独立协程：持续消费 SSE 队列，即时处理每个事件"""
        while True:
            evt = await sse_queue.get()
            if "_error" in evt:
                await ws.send(json.dumps({
                    "op": "log", "level": "warning",
                    "message": f"SSE 断开: {evt['_error']}，3 秒后重连…",
                }))
                await asyncio.sleep(3)
                sse_start(cfg["endpoint"])
                continue

            cur = evt.get("miss", 0)
            st  = evt.get("status", "")
            jc  = evt.get("critical", 0)
            js  = evt.get("justice", 0)
            at  = evt.get("attack", 0)

            if state["first_event"]:
                state["first_event"] = False
                await ws.send(json.dumps({
                    "op": "log", "level": "info",
                    "message": f"SSE 已连接: miss={cur} jc={jc} js={js} at={at} status={st}",
                }))

            if cfg["debug"]:
                changed = (
                    st != state["last_status"]
                    or cur != state["last_debug"]["miss"]
                    or jc != state["last_debug"]["critical"]
                    or js != state["last_debug"]["justice"]
                    or at != state["last_debug"]["attack"]
                )
                if changed:
                    await ws.send(json.dumps({
                        "op": "log", "level": "debug",
                        "message": f"更新: miss={cur} jc={jc} js={js} at={at} status={st}",
                    }))
                    state["last_status"] = st
                    state["last_debug"] = {"miss": cur, "critical": jc, "justice": js, "attack": at}

            last_miss = state["last_miss"]

            # 新一局（miss 清零）
            if cur == 0 and last_miss > 0:
                await ws.send(json.dumps({
                    "op": "log", "level": "info",
                    "message": f"新一局，上局 MISS={last_miss}",
                }))
                await ws.send(json.dumps({
                    "op": "set_strength",
                    "channel": cfg["channel"],
                    "pct": 0,
                }))

            # MISS 增加 → 触发硬件
            if cur > last_miss:
                pct = calc_strength(jc, js, at, cur)
                if cfg["debug"]:
                    # 函数模式时输出中间变量，方便排查公式问题
                    if cfg["mode"] == "function":
                        try:
                            ns = {"jc": jc, "j": js, "a": at, "m": cur, **MATH_FUNCS}
                            y = eval(cfg["formula"], {"__builtins__": {}}, ns)
                            await ws.send(json.dumps({
                                "op": "log", "level": "debug",
                                "message": f"CALC: formula={cfg['formula']} | m={cur} → y={y:.3f} → pct={pct}",
                            }))
                        except Exception as exc:
                            await ws.send(json.dumps({
                                "op": "log", "level": "error",
                                "message": f"CALC ERROR: {exc}",
                            }))
                if pct > 0:
                    await ws.send(json.dumps({
                        "op": "trigger",
                        "action": "both",
                        "delta_pct": pct,
                        "strength_mode": "rollback",
                        "duration_s": cfg["duration_s"],
                        "channel": cfg["channel"],
                        "label": f"MISS ×{cur} @ {pct}%",
                    }))
                if cfg["debug"]:
                    await ws.send(json.dumps({
                        "op": "log", "level": "debug",
                        "message": f"TRIGGER: miss {last_miss}→{cur} | mode={cfg['mode']} | delta={pct}% | dur={cfg['duration_s']}s | ch={cfg['channel']}",
                    }))
                await ws.send(json.dumps({
                    "op": "status",
                    "fields": {
                        "display_status": f"MISS={cur} | {pct}%",
                        "miss": cur,
                        "strength_pct": pct,
                    },
                }))

            state["last_miss"] = cur

    # ── WebSocket 主循环 ──
    uri = f"ws://{host}:{port}/ws/plugin?token={token}"
    async with websockets.connect(uri) as ws:
        # 1. 握手
        await ws.send(json.dumps({
            "op": "hello",
            "token": token,
            "manifest": {
                "id": os.environ.get("DGHUB_PLUGIN_ID", "chuni2_hardware"),
                "name": "CHUNITHM 硬件联动",
                "version": "0.1.0",
                "sdk": "1",
            },
        }))
        ack = json.loads(await ws.recv())
        if not ack.get("accepted"):
            raise RuntimeError(ack.get("reason", "hello rejected"))

        await ws.send(json.dumps({
            "op": "log", "level": "info",
            "message": "插件已就绪",
        }))

        # 2. 启动 SSE 处理器（独立协程，与 WS 循环并行）
        sse_task = asyncio.create_task(sse_processor(ws))

        try:
            async for raw in ws:
                msg = json.loads(raw)
                op = msg.get("op")

                if op == "stop":
                    break

                if op == "config":
                    for k in cfg:
                        if k in msg.get("data", {}):
                            cfg[k] = msg["data"][k]
                    await ws.send(json.dumps({
                        "op": "log", "level": "info",
                        "message": f"配置: endpoint={cfg['endpoint']}, mode={cfg['mode']}, dur={cfg['duration_s']}s, ch={cfg['channel']}, debug={cfg['debug']}",
                    }))
                    if sse_thread[0] is None:
                        sse_start(cfg["endpoint"])

                elif op == "config_changed":
                    key = msg.get("key")
                    val = msg.get("value")
                    if key in cfg:
                        cfg[key] = val
                        await ws.send(json.dumps({
                            "op": "log", "level": "info",
                            "message": f"配置变更: {key} = {val}",
                        }))
                        if key == "endpoint":
                            sse_stopper()
                            sse_start(cfg["endpoint"])

                elif op == "ping":
                    await ws.send(json.dumps({"op": "pong", "t": msg.get("t")}))
        finally:
            sse_task.cancel()
            try:
                await sse_task
            except asyncio.CancelledError:
                pass
            sse_stopper()


if __name__ == "__main__":
    asyncio.run(main())
