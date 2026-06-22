// chuni_overlay.cpp
// 直接翻译自 chuni.py v2，逻辑完全一致。
// 进程内用 VirtualQuery 枚举区域，搜 NUM_xxx\0 签名，偏移 +0x238 读 u16。
//
// 编译:
//   C:\msys64\mingw32\bin\g++.exe -shared -o chuni_overlay.asi chuni_overlay.cpp ^
//       -lws2_32 -static -static-libgcc -static-libstdc++ -O2
//
// 部署: 放游戏 bin 目录。浏览器 http://localhost:8888

#include <winsock2.h>
#include <windows.h>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdarg>
#include <atomic>

// ── 配置 (完全照 Python 版) ────────────────────────────
#define VALUE_OFFSET   0x238
#define MARKER_OFFSET  (VALUE_OFFSET - 4)   // 0x234, 应为 03 00 00 00
#define SCAN_MIN_ADDR  0x50000000u
#define MAX_HITS       3
#define HTTP_PORT      8888

static const uint8_t MARKER[4] = {0x03, 0x00, 0x00, 0x00};

// 签名: NUM_xxx\0，含结尾 \0
struct Sig { const char* key; const char* sig; int len; };
static Sig SIGS[4] = {
    { "jctirical", "NUM_jctirical\x00", 14 },
    { "ctirical",  "NUM_ctirical\x00",  13 },
    { "attack",    "NUM_attack\x00",    11 },
    { "miss",      "NUM_miss\x00",       9 },
};

// ── 日志 ──────────────────────────────────────────────
static void logf(const char* fmt, ...) {
    FILE* f = fopen("chuni_log.txt", "a"); if (!f) return;
    va_list ap; va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
    fprintf(f, "\n"); fclose(f);
}

// ── 共享数据 ──────────────────────────────────────────
static std::atomic<int> g_critical{0}, g_justice{0}, g_attack{0}, g_miss{0};
static char g_status[64] = "init";
static CRITICAL_SECTION g_cs;
static void setStatus(const char* s) {
    EnterCriticalSection(&g_cs);
    strncpy(g_status, s, 63); g_status[63] = 0;
    LeaveCriticalSection(&g_cs);
}

// ── iter_regions: 完全照 Python iter_regions ──────────
// Python: state==MEM_COMMIT and (prot&0xFF) in {2,4,0x20,0x40} and rsize>0 and base>=0x50000000
// 枚举后 ReadProcessMemory 读出整块数据 → C++ 里直接指针访问 (在进程内, 无需 RPM)
// 为了安全, 用 VirtualQuery 判定可读后再访问

struct Region { uintptr_t base; size_t size; };

static void iterRegions(Region* out, int& count, int maxCount) {
    count = 0;
    MEMORY_BASIC_INFORMATION mbi;
    uintptr_t addr = 0;
    static const DWORD READABLE[] = {
        PAGE_READONLY, PAGE_READWRITE,
        PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE
    };

    while (addr < 0x7FFF0000u && count < maxCount) {
        if (!VirtualQuery((void*)addr, &mbi, sizeof(mbi))) {
            addr += 0x1000; continue;
        }
        uintptr_t base  = (uintptr_t)mbi.BaseAddress;
        size_t    rsize = mbi.RegionSize;
        uintptr_t nxt   = (rsize > 0) ? base + rsize : addr + 0x1000;

        DWORD prot = mbi.Protect & 0xFF;
        bool readable = (mbi.State == MEM_COMMIT) && (rsize > 0) &&
                        !(mbi.Protect & PAGE_GUARD);
        if (readable) {
            bool protOk = false;
            for (int i = 0; i < 4; i++) if (prot == READABLE[i]) { protOk = true; break; }
            readable = protOk;
        }
        // 对应 Python: base >= 0x50000000
        if (readable && base >= SCAN_MIN_ADDR) {
            out[count++] = { base, rsize };
        }
        addr = (nxt > addr) ? nxt : addr + 0x1000;
    }
}

static bool findFields(uintptr_t found[4]) {
    struct Hit { uintptr_t addr; uint16_t val; };
    Hit hits[4][MAX_HITS];
    int hitCnt[4] = {0,0,0,0};

    MEMORY_BASIC_INFORMATION mbi;
    uintptr_t addr = 0;
    static const DWORD READABLE[] = {
        PAGE_READONLY, PAGE_READWRITE,
        PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE
    };

    while (addr < 0xFFFF0000u) {
        if (!VirtualQuery((void*)addr, &mbi, sizeof(mbi))) {
            addr += 0x1000; continue;
        }
        uintptr_t base  = (uintptr_t)mbi.BaseAddress;
        size_t    rsize = mbi.RegionSize;
        uintptr_t nxt   = (rsize > 0) ? base + rsize : addr + 0x1000;

        DWORD prot = mbi.Protect & 0xFF;
        bool readable = (mbi.State == MEM_COMMIT) && (rsize > 0) &&
                        !(mbi.Protect & PAGE_GUARD);
        if (readable) {
            bool ok = false;
            for (int i = 0; i < 4; i++) if (prot == READABLE[i]) { ok = true; break; }
            readable = ok;
        }

        // 对应 Python: base >= 0x50000000
        if (readable && base >= SCAN_MIN_ADDR) {
            const uint8_t* p = (const uint8_t*)base;

            bool allDone = true;
            for (int si = 0; si < 4; si++)
                if (hitCnt[si] < MAX_HITS) { allDone = false; break; }
            if (allDone) break;

            for (int si = 0; si < 4; si++) {
                if (hitCnt[si] >= MAX_HITS) continue;
                const char* sig    = SIGS[si].sig;
                int         siglen = SIGS[si].len;
                size_t off = 0;
                while (hitCnt[si] < MAX_HITS && off + siglen <= rsize) {
                    const uint8_t* fp = (const uint8_t*)memchr(p + off,
                                        (uint8_t)sig[0], rsize - off - siglen + 1);
                    if (!fp) break;
                    size_t pos = fp - p;
                    if (pos + siglen > rsize) break;
                    if (memcmp(p + pos, sig, siglen) == 0) {
                        size_t marker_off = pos + MARKER_OFFSET;
                        if (marker_off + 4 <= rsize &&
                            memcmp(p + marker_off, MARKER, 4) == 0) {
                            uintptr_t valAddr = base + pos + VALUE_OFFSET;
                            hits[si][hitCnt[si]++] = { valAddr, *(uint16_t*)valAddr };
                        }
                    }
                    off = pos + 1;
                }
            }
        }
        addr = (nxt > addr) ? nxt : addr + 0x1000;
    }

    for (int si = 0; si < 4; si++) {
        if (hitCnt[si] == 0) return false;
        uintptr_t best = 0;
        for (int i = 0; i < hitCnt[si]; i++)
            if (hits[si][i].addr >= SCAN_MIN_ADDR && hits[si][i].addr > best)
                best = hits[si][i].addr;
        if (!best) return false;
        found[si] = best;
    }
    logf("findFields ok: jc=%p js=%p at=%p ms=%p",
         (void*)found[0],(void*)found[1],(void*)found[2],(void*)found[3]);
    return true;
}

// ── HTTP + SSE ────────────────────────────────────────
static void sendAll(SOCKET s, const char* b, int n) {
    int t = 0; while (t < n) { int k = send(s, b+t, n-t, 0); if (k<=0) break; t+=k; }
}

static void buildJson(char* buf, int len) {
    EnterCriticalSection(&g_cs);
    snprintf(buf, len,
        "{\"critical\":%d,\"justice\":%d,\"attack\":%d,\"miss\":%d,\"status\":\"%s\"}",
        g_critical.load(), g_justice.load(), g_attack.load(), g_miss.load(), g_status);
    LeaveCriticalSection(&g_cs);
}

static const char HTML[] =
"<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>CHUNITHM</title>"
"<style>*{box-sizing:border-box;margin:0;padding:0}"
"body{background:#0a0a0f;color:#e0e0e0;font-family:'IBM Plex Mono','Courier New',monospace;"
"display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:2vh}"
".row{display:flex;align-items:baseline;gap:2vw;font-size:4vw}"
".label{color:#555;font-size:2vw;letter-spacing:2px}"
".val{color:#ffd24a;font-weight:bold;min-width:5ch;text-align:right}"
".miss .val{color:#ff5a5a}.atk .val{color:#ff9a3a}.jst .val{color:#3acfff}.jc .val{color:#c8ff3a}"
".status{color:#444;font-size:1.4vw;position:fixed;bottom:2vh}</style></head><body>"
"<div class=\"row jc\"><span class=\"label\">JUSTICE CRITICAL</span><span class=\"val\" id=\"jc\">-</span></div>"
"<div class=\"row jst\"><span class=\"label\">JUSTICE</span><span class=\"val\" id=\"js\">-</span></div>"
"<div class=\"row atk\"><span class=\"label\">ATTACK</span><span class=\"val\" id=\"at\">-</span></div>"
"<div class=\"row miss\"><span class=\"label\">MISS</span><span class=\"val\" id=\"ms\">-</span></div>"
"<div class=\"status\" id=\"st\">init</div>"
"<script>const es=new EventSource('/events');"
"es.onmessage=e=>{const d=JSON.parse(e.data);"
"jc.textContent=d.critical;js.textContent=d.justice;at.textContent=d.attack;"
"ms.textContent=d.miss;st.textContent=d.status}</script></body></html>";

static DWORD WINAPI clientThread(LPVOID param) {
    SOCKET c = (SOCKET)(uintptr_t)param;
    char req[2048];
    int n = recv(c, req, sizeof(req)-1, 0);
    if (n <= 0) { closesocket(c); return 0; }
    req[n] = 0;

    if (strncmp(req, "GET /events", 11) == 0) {
        const char* hdr =
            "HTTP/1.1 200 OK\r\nContent-Type:text/event-stream\r\n"
            "Cache-Control:no-cache\r\nAccess-Control-Allow-Origin:*\r\n"
            "Connection:keep-alive\r\n\r\n";
        sendAll(c, hdr, (int)strlen(hdr));
        char json[256], msg[320];
        for (;;) {
            buildJson(json, sizeof(json));
            int m = snprintf(msg, sizeof(msg), "data: %s\n\n", json);
            if (send(c, msg, m, 0) <= 0) break;
            Sleep(50);
        }
    } else {
        const char* body; const char* ct;
        char json[256];
        if (strncmp(req, "GET /data", 9) == 0) {
            buildJson(json, sizeof(json)); body = json; ct = "application/json";
        } else {
            body = HTML; ct = "text/html; charset=utf-8";
        }
        char hdr[256];
        int hl = snprintf(hdr, sizeof(hdr),
            "HTTP/1.1 200 OK\r\nContent-Type:%s\r\n"
            "Access-Control-Allow-Origin:*\r\nContent-Length:%d\r\n"
            "Connection:close\r\n\r\n", ct, (int)strlen(body));
        sendAll(c, hdr, hl);
        sendAll(c, body, (int)strlen(body));
    }
    closesocket(c);
    return 0;
}

static DWORD WINAPI httpThread(LPVOID) {
    WSADATA w; if (WSAStartup(MAKEWORD(2,2), &w)) return 0;
    SOCKET srv = socket(AF_INET, SOCK_STREAM, 0);
    BOOL o = TRUE; setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, (char*)&o, sizeof(o));
    sockaddr_in a{}; a.sin_family = AF_INET;
    a.sin_addr.s_addr = INADDR_ANY; a.sin_port = htons(HTTP_PORT);
    if (bind(srv,(sockaddr*)&a,sizeof(a)) == SOCKET_ERROR) { logf("bind fail"); return 0; }
    listen(srv, 8);
    logf("http on %d", HTTP_PORT);
    for (;;) {
        SOCKET c = accept(srv, 0, 0);
        if (c != INVALID_SOCKET)
            CreateThread(0, 0, clientThread, (LPVOID)(uintptr_t)c, 0, 0);
    }
}

// ── 扫描+读取主循环 (照 Python main 的 while True 双层循环) ──
static DWORD WINAPI scanThread(LPVOID) {
    Sleep(5000);
    logf("scan thread start");

    // 先诊断: 枚举所有区域记录最高地址
    {
        MEMORY_BASIC_INFORMATION mbi;
        uintptr_t addr = 0, maxBase = 0;
        int cnt = 0;
        while (addr < 0xFFFF0000u) {
            if (!VirtualQuery((void*)addr, &mbi, sizeof(mbi))) { addr += 0x1000; continue; }
            uintptr_t base = (uintptr_t)mbi.BaseAddress;
            size_t size = mbi.RegionSize;
            if (mbi.State == MEM_COMMIT && base >= SCAN_MIN_ADDR) {
                cnt++;
                if (base > maxBase) maxBase = base;
            }
            uintptr_t nxt = base + size;
            addr = (nxt > addr) ? nxt : addr + 0x1000;
        }
        logf("diagnostic: %d regions >= 0x50000000, maxBase=%p", cnt, (void*)maxBase);
    }

    for (;;) {
        // 对应 Python: while not addrs: addrs = find_fields(...)
        setStatus("scanning...");
        uintptr_t addrs[4] = {0};
        int attempts = 0;
        while (!findFields(addrs)) {
            attempts++;
            // logf("  attempt %d not found, retry...", attempts);
            Sleep(1500);
        }
        logf("found: jc=%p js=%p at=%p ms=%p",
             (void*)addrs[0],(void*)addrs[1],(void*)addrs[2],(void*)addrs[3]);
        setStatus("reading");

        // 对应 Python: while True 读取循环
        for (;;) {
            // 对应 Python: read_u16(handle, addr) — 进程内直接读
            uint16_t jc = *(uint16_t*)addrs[0];
            uint16_t js = *(uint16_t*)addrs[1];
            uint16_t at = *(uint16_t*)addrs[2];
            uint16_t ms = *(uint16_t*)addrs[3];

            // 垃圾值 > 30000 视为 0
            int vjc = jc > 30000 ? 0 : jc;
            int vjs = js > 30000 ? 0 : js;
            int vat = at > 30000 ? 0 : at;
            int vms = ms > 30000 ? 0 : ms;

            g_critical = vjc; g_justice = vjs; g_attack = vat; g_miss = vms;

            if (vjc == vjs && vjs == vat && vat == vms)
                setStatus("IN MENU");
            else
                setStatus("PLAYING");

            Sleep(50);  // 20Hz
        }
        // 注: Python 版靠 read_u16 返回 None 检测内存释放后 break
        // 进程内直接读不会返回 None，所以这里暂时不 break，持续读取
        // 如需重扫，改成检测 jc>30000 && ms>30000 连续多次触发
    }
}

BOOL APIENTRY DllMain(HMODULE h, DWORD r, LPVOID) {
    if (r == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(h);
        InitializeCriticalSection(&g_cs);
        CreateThread(0, 0, httpThread, 0, 0, 0);
        CreateThread(0, 0, scanThread, 0, 0, 0);
    }
    return TRUE;
}