"""
chunithm_overlay.py  v2
直接搜内存里的字段名签名 (NUM_jctirical\0 等)，定位判定计数地址。
比「扫99999等归零」更稳定，不依赖初始值，不需要手动按回车。

pip install psutil
python chunithm_overlay.py
浏览器: http://localhost:8888
"""

import ctypes, struct, time, threading, json, psutil
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# ── 签名 → 值偏移 ──────────────────────────────────────────────
# CE 验证：签名字节起始地址 + 0x238 = 2字节小端计数值
VALUE_OFFSET = 0x238

SIGS = {
    "jctirical": b"NUM_jctirical\x00",   # JUSTICE CRITICAL
    "ctirical":  b"NUM_ctirical\x00",    # JUSTICE
    "attack":     b"NUM_attack\x00",       # ATTACK
    "miss":       b"NUM_miss\x00",         # MISS
}

# ── Windows API ─────────────────────────────────────────────────
k32 = ctypes.windll.kernel32
k32.ReadProcessMemory.argtypes  = [ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualQueryEx.argtypes     = [ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_size_t]

# 自动适配 Python 位数 → MBI 布局
IS64 = ctypes.sizeof(ctypes.c_void_p) == 8
if IS64:
    MBI_SIZE = 48;  PFMT = '<Q'
    OFF_BASE, OFF_SIZE, OFF_STATE, OFF_PROT, OFF_TYPE = 0, 24, 32, 36, 40
else:
    MBI_SIZE = 28;  PFMT = '<I'
    OFF_BASE, OFF_SIZE, OFF_STATE, OFF_PROT, OFF_TYPE = 0, 12, 16, 20, 24

MEM_COMMIT = 0x1000
READABLE   = {0x02, 0x04, 0x20, 0x40}   # PAGE_READONLY/RW/EXECUTE_READ/EXECUTE_RW

def get_pid(name="chusanApp.exe"):
    for p in psutil.process_iter(['pid', 'name']):
        if name.lower() in (p.info['name'] or '').lower():
            return p.info['pid']
    return None

def open_proc(pid):
    return k32.OpenProcess(0x0010 | 0x0400, False, pid)

def read_u16(handle, addr):
    buf = ctypes.create_string_buffer(2)
    n   = ctypes.c_size_t(0)
    if k32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, 2, ctypes.byref(n)) and n.value == 2:
        return struct.unpack('<H', buf.raw)[0]
    return None

def iter_regions(handle):
    """枚举所有 COMMIT 可读内存区域，yield (base, bytes)"""
    addr = 0
    mbi  = ctypes.create_string_buffer(MBI_SIZE)
    MAX  = 0x7FFFFFFF if not IS64 else 0x7FFFFFFFFFFF
    while addr < MAX:
        if k32.VirtualQueryEx(handle, ctypes.c_void_p(addr), mbi, MBI_SIZE) == 0:
            addr += 0x1000
            continue
        base  = struct.unpack_from(PFMT, mbi, OFF_BASE)[0]
        rsize = struct.unpack_from(PFMT, mbi, OFF_SIZE)[0]
        state = struct.unpack_from('<I',  mbi, OFF_STATE)[0]
        prot  = struct.unpack_from('<I',  mbi, OFF_PROT)[0]
        nxt   = base + rsize if rsize > 0 else addr + 0x1000
        if (state == MEM_COMMIT and (prot & 0xFF) in READABLE and rsize > 0
                and base >= 0x50000000):  # 跳过静态区，不读
            buf = ctypes.create_string_buffer(rsize)
            n   = ctypes.c_size_t(0)
            if k32.ReadProcessMemory(handle, ctypes.c_void_p(base), buf, rsize, ctypes.byref(n)) and n.value > 0:
                yield base, buf.raw[:n.value]
        addr = nxt if nxt > addr else addr + 0x1000

def find_fields(handle):
    """返回 {key: 值地址} 四个都找到才返回，否则返回 {}"""
    MAX_HITS = 3
    MARKER = b'\x03\x00\x00\x00'
    all_hits = {key: [] for key in SIGS}
    for base, data in iter_regions(handle):
        if base < 0x50000000:
            continue
        if all(len(h) >= MAX_HITS for h in all_hits.values()):
            break
        for key in SIGS:
            if len(all_hits[key]) >= MAX_HITS:
                continue
            off = 0
            while len(all_hits[key]) < MAX_HITS:
                pos = data.find(SIGS[key], off)
                if pos == -1:
                    break
                addr = base + pos + VALUE_OFFSET
                marker_off = pos + VALUE_OFFSET - 4
                if (marker_off >= 0 and
                    data[marker_off:marker_off+4] == MARKER):
                    val = read_u16(handle, addr)
                    all_hits[key].append((addr, val))
                off = pos + 1

    found = {}
    for key, hits in all_hits.items():
        if not hits:
            return {}
        # 丢弃低地址的静态模板实例（< 0x50000000），只保留运行时实例
        hits = [(a, v) for a, v in hits if a >= 0x50000000]
        if not hits:
            return {}
        # 取地址最高的（堆上运行时实例）
        found[key] = max(hits, key=lambda x: x[0])[0]
    return found

# ── 全局数据 ────────────────────────────────────────────────────
g      = {"critical": 0, "justice": 0, "attack": 0, "miss": 0, "status": "init"}
g_lock = threading.Lock()

def setstatus(s):
    with g_lock: g['status'] = s
    print(s)

# ── HTTP server ──────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>CHUNITHM</title>
<style>*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0f;color:#e0e0e0;font-family:'IBM Plex Mono','Courier New',monospace;
display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:2vh}
.row{display:flex;align-items:baseline;gap:2vw;font-size:4vw}
.label{color:#555;font-size:2vw;letter-spacing:2px}
.val{color:#ffd24a;font-weight:bold;min-width:5ch;text-align:right}
.miss .val{color:#ff5a5a}.atk .val{color:#ff9a3a}.jst .val{color:#3acfff}.jc .val{color:#c8ff3a}
.status{color:#444;font-size:1.4vw;position:fixed;bottom:2vh}</style></head><body>
<div class="row jc"><span class="label">JUSTICE CRITICAL</span><span class="val" id="jc">-</span></div>
<div class="row jst"><span class="label">JUSTICE</span><span class="val" id="js">-</span></div>
<div class="row atk"><span class="label">ATTACK</span><span class="val" id="at">-</span></div>
<div class="row miss"><span class="label">MISS</span><span class="val" id="ms">-</span></div>
<div class="status" id="st">init</div>
<script>const es=new EventSource('/events');
es.onmessage=e=>{const d=JSON.parse(e.data);
jc.textContent=d.critical;js.textContent=d.justice;at.textContent=d.attack;
ms.textContent=d.miss;st.textContent=d.status}</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                while True:
                    with g_lock: body = json.dumps(g).encode()
                    self.wfile.write(b'data: ' + body + b'\n\n')
                    self.wfile.flush()
                    time.sleep(0.05)
            except: pass
            return
        if self.path == '/data':
            with g_lock: body = json.dumps(g).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

# ── 主循环 ──────────────────────────────────────────────────────
def main():
    threading.Thread(
        target=lambda: ThreadingHTTPServer(('0.0.0.0', 8888), H).serve_forever(),
        daemon=True).start()
    print("网页: http://localhost:8888")
    print(f"Python {'64' if IS64 else '32'}位  MBI_SIZE={MBI_SIZE}")

    setstatus("等待游戏...")
    handle = None
    while not handle:
        pid = get_pid()
        if pid:
            handle = open_proc(pid)
            print(f"连接 PID={pid}")
        else:
            time.sleep(1)

    while True:
        setstatus("扫描字段名签名（需在打歌中途）...")
        addrs    = {}
        attempts = 0
        while not addrs:
            addrs = find_fields(handle)
            attempts += 1
            if not addrs:
                print(f"  第{attempts}次未找到，1.5秒后重试...")
                time.sleep(1.5)

        for k, a in addrs.items():
            print(f"  {k} -> {hex(a)}")
        setstatus("实时读取中")

        while True:
            jc = read_u16(handle, addrs['jctirical'])
            js = read_u16(handle, addrs['ctirical'])
            at = read_u16(handle, addrs['attack'])
            ms = read_u16(handle, addrs['miss'])

            if None in (jc, js, at, ms):   # 内存释放 = 这局结束
                setstatus("等待下一局...")
                time.sleep(1)
                break

            # 垃圾值（> 30000）视为 0
            if jc > 30000: jc = 0
            if js > 30000: js = 0
            if at > 30000: at = 0
            if ms > 30000: ms = 0

            # 合理性检查：四个值完全相等 → 在菜单界面，等数据出现就好
            if jc == js == at == ms:
                with g_lock:
                    g['critical'] = jc
                    g['justice']  = js
                    g['attack']   = at
                    g['miss']     = ms
                    g['status']   = "IN MENU"
                time.sleep(0.05)
                continue  # 地址没错，继续读取即可

            with g_lock:
                g['critical'] = jc
                g['justice']  = js
                g['attack']   = at
                g['miss']     = ms
                g['status']   = "PLAYING"
            print(f"\rJC={jc:3d} JS={js:3d} AT={at:3d} MS={ms:3d}", end='', flush=True)
            time.sleep(0.05)   # 20Hz

if __name__ == '__main__':
    main()