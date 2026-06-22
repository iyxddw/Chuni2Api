"""
overlay_server.py
chuni.py 的前端服务，独立运行，不改 chuni.py。

工作方式：
  浏览器 ──> 本服务(:8889) ──流式代理──> chuni.py(:8888)/events
  /        返回 overlay 页面（同源，无跨源 / MIME 问题）
  /events  流式代理上游 SSE
  /data    代理一次性 JSON

用法：
  1. 先跑 chuni.py（监听 8888）
  2. python overlay_server.py
  3. 浏览器开 http://localhost:8889

只依赖标准库。
"""

import http.client
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 8888          # chuni.py
LISTEN_PORT   = 8889          # 本服务

# ── overlay 页面（ENDPOINT="" 同源）────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CHUNITHM // judgement.bin</title>
<style>
:root{
  --bg:#0a0a0f; --fg:#e0e0e0; --dim:#555; --dimmer:#333;
  --line:#1a1a22; --accent:#ffd24a;
  --jc:#c8ff3a; --js:#3acfff; --at:#ff9a3a; --ms:#ff5a5a;
  --ok:#4ade80; --bad:#ff5a5a;
  --addr:#5a5a72; --byte:#7a7a92;
}
html[data-theme="light"]{
  --bg:#f4f4f0; --fg:#1a1a1a; --dim:#999; --dimmer:#ccc;
  --line:#e2e2da; --accent:#b8860b;
  --jc:#5a8c00; --js:#0077a8; --at:#c25e00; --ms:#c0392b;
  --addr:#a0a090; --byte:#888;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  background:var(--bg);color:var(--fg);
  font-family:'IBM Plex Mono','SFMono-Regular','Courier New',monospace;
  font-feature-settings:"tnum" 1,"zero" 1;
  font-size:14px;line-height:1.4;
  display:flex;flex-direction:column;
  -webkit-font-smoothing:antialiased;
  transition:background .25s,color .25s;
  overflow:hidden;
}
header{
  display:flex;align-items:center;gap:1ch;
  padding:14px 20px;border-bottom:1px solid var(--line);
  font-size:12px;color:var(--dim);user-select:none;
}
header .brand{color:var(--fg);letter-spacing:1px}
header .brand b{color:var(--accent);font-weight:700}
header .spacer{flex:1}
.dot{width:7px;height:7px;border-radius:50%;background:var(--bad);
  box-shadow:0 0 0 0 currentColor;color:var(--bad)}
.dot.live{background:var(--ok);color:var(--ok);animation:pulse 1.8s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 currentColor}70%{box-shadow:0 0 0 5px transparent}100%{box-shadow:0 0 0 0 transparent}}
.statusword{color:var(--dim);letter-spacing:1px;min-width:11ch}
.statusword.playing{color:var(--jc)}
.statusword.menu{color:var(--at)}
button.toggle{
  background:none;border:1px solid var(--line);color:var(--dim);
  font-family:inherit;font-size:11px;padding:3px 9px;cursor:pointer;
  letter-spacing:1px;transition:border .2s,color .2s;
}
button.toggle:hover{border-color:var(--dim);color:var(--fg)}
main{flex:1;display:flex;flex-direction:column;justify-content:center;
  padding:0 clamp(16px,5vw,80px);gap:clamp(6px,1.4vh,18px);min-height:0}
.row{
  display:grid;
  grid-template-columns: 3ch 11ch 1fr auto;
  align-items:center;gap:clamp(8px,2vw,28px);
  padding:clamp(6px,1.2vh,14px) 0;
  border-bottom:1px dashed var(--line);
}
.row .idx{color:var(--addr);font-size:.72em}
.row .lbl{color:var(--dim);font-size:clamp(10px,1.3vw,14px);letter-spacing:1.5px;white-space:nowrap}
.row .bar{height:3px;background:var(--dimmer);position:relative;overflow:hidden;border-radius:2px}
.row .bar>i{position:absolute;left:0;top:0;bottom:0;width:0;background:currentColor;
  transition:width .18s ease-out;opacity:.7}
.row .val{
  font-size:clamp(28px,6vw,72px);font-weight:700;text-align:right;
  min-width:6ch;letter-spacing:-1px;font-variant-numeric:tabular-nums;
  transition:text-shadow .15s,transform .12s;
}
.row.flash .val{transform:translateY(-2px);text-shadow:0 0 18px currentColor}
.jc{color:var(--jc)} .js{color:var(--js)} .at{color:var(--at)} .ms{color:var(--ms)}
.row .lbl,.row .idx{color:var(--dim)}
.derived{
  display:flex;flex-wrap:wrap;gap:clamp(12px,3vw,48px);
  padding:clamp(8px,1.6vh,18px) 0 0;margin-top:clamp(4px,1vh,10px);
  border-top:1px solid var(--line);justify-content:flex-start;
}
.stat{display:flex;flex-direction:column;gap:2px}
.stat .k{color:var(--dim);font-size:10px;letter-spacing:2px}
.stat .v{color:var(--fg);font-size:clamp(16px,2.4vw,26px);font-weight:700;font-variant-numeric:tabular-nums}
.stat.acc .v{color:var(--accent)}
footer{
  border-top:1px solid var(--line);padding:10px 20px;
  font-size:11px;color:var(--byte);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;user-select:none;
}
footer .addr{color:var(--addr)}
footer .sep{color:var(--dimmer);margin:0 1ch}
</style>
</head>
<body>
<header>
  <span class="brand"><b>judgement</b>.bin</span>
  <span class="sep" style="color:var(--dimmer)">::</span>
  <span class="dot" id="dot"></span>
  <span class="statusword" id="statusword">offline</span>
  <span class="spacer"></span>
  <span id="rate" style="color:var(--dim)">0 Hz</span>
  <button class="toggle" id="theme">[ THEME ]</button>
</header>

<main>
  <div class="row jc" data-key="critical">
    <span class="idx">00</span><span class="lbl">JUSTICE CRIT</span>
    <span class="bar"><i></i></span><span class="val">0</span>
  </div>
  <div class="row js" data-key="justice">
    <span class="idx">01</span><span class="lbl">JUSTICE</span>
    <span class="bar"><i></i></span><span class="val">0</span>
  </div>
  <div class="row at" data-key="attack">
    <span class="idx">02</span><span class="lbl">ATTACK</span>
    <span class="bar"><i></i></span><span class="val">0</span>
  </div>
  <div class="row ms" data-key="miss">
    <span class="idx">03</span><span class="lbl">MISS</span>
    <span class="bar"><i></i></span><span class="val">0</span>
  </div>

  <div class="derived">
    <div class="stat"><span class="k">TOTAL</span><span class="v" id="d_total">0</span></div>
    <div class="stat acc"><span class="k">ACCURACY</span><span class="v" id="d_acc">&mdash;</span></div>
    <div class="stat"><span class="k">JC RATE</span><span class="v" id="d_jcr">&mdash;</span></div>
    <div class="stat"><span class="k">NON-JC</span><span class="v" id="d_njc">0</span></div>
  </div>
</main>

<footer id="hex">
  <span class="addr">0x00000000</span><span class="sep">|</span>waiting for stream&hellip;
</footer>

<script>
"use strict";
const ENDPOINT = "";                 // 同源，由本代理服务提供
const KEYS = ["critical","justice","attack","miss"];

const root = document.documentElement;
const savedTheme = (function(){ try{return localStorage.getItem("ov_theme")}catch(e){return null} })();
if(savedTheme) root.setAttribute("data-theme", savedTheme);
document.getElementById("theme").onclick = () => {
  const cur = root.getAttribute("data-theme") === "light" ? "" : "light";
  if(cur) root.setAttribute("data-theme", cur); else root.removeAttribute("data-theme");
  try{ localStorage.setItem("ov_theme", cur) }catch(e){}
};

const rows = {};
document.querySelectorAll(".row").forEach(r => {
  rows[r.dataset.key] = { el:r, val:r.querySelector(".val"), bar:r.querySelector(".bar>i") };
});
const elDot    = document.getElementById("dot");
const elStatus = document.getElementById("statusword");
const elRate   = document.getElementById("rate");
const elHex    = document.getElementById("hex");
const d_total  = document.getElementById("d_total");
const d_acc    = document.getElementById("d_acc");
const d_jcr    = document.getElementById("d_jcr");
const d_njc    = document.getElementById("d_njc");

const disp   = { critical:0, justice:0, attack:0, miss:0 };
const target = { critical:0, justice:0, attack:0, miss:0 };
let lastSeen = { critical:0, justice:0, attack:0, miss:0 };

function tick(){
  for(const k of KEYS){
    const cur = disp[k], tgt = target[k];
    if(cur !== tgt){
      const step = Math.max(1, Math.ceil(Math.abs(tgt-cur)/4));
      disp[k] = cur < tgt ? Math.min(tgt, cur+step) : Math.max(tgt, cur-step);
      rows[k].val.textContent = disp[k];
    }
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

function render(){
  const c=target.critical, j=target.justice, a=target.attack, m=target.miss;
  const total = c+j+a+m, nonjc = j+a+m;
  d_total.textContent = total;
  d_njc.textContent   = nonjc;
  if(total>0){
    const acc = (c*1 + j*0.985 + a*0.5 + m*0) / total * 100;
    d_acc.textContent = acc.toFixed(2)+"%";
    d_jcr.textContent = (c/total*100).toFixed(1)+"%";
  } else { d_acc.textContent="\u2014"; d_jcr.textContent="\u2014"; }
  const mx = Math.max(1, c, j, a, m);
  rows.critical.bar.style.width = (c/mx*100)+"%";
  rows.justice .bar.style.width = (j/mx*100)+"%";
  rows.attack  .bar.style.width = (a/mx*100)+"%";
  rows.miss    .bar.style.width = (m/mx*100)+"%";
}

function hexline(){
  const order=["critical","justice","attack","miss"];
  const bytes=[];
  for(const k of order){ const v=target[k]&0xFFFF; bytes.push(v&0xFF,(v>>8)&0xFF); }
  const hx  = bytes.map(b=>b.toString(16).padStart(2,"0")).join(" ");
  const asc = bytes.map(b=> (b>=32&&b<127)? String.fromCharCode(b):".").join("");
  elHex.innerHTML =
    '<span class="addr">0x'+ (Date.now()&0xFFFFFFFF).toString(16).padStart(8,"0") +
    '</span><span class="sep">|</span>'+ hx +
    '<span class="sep">|</span>'+ asc;
}

function flash(k){
  const r = rows[k].el;
  r.classList.remove("flash"); void r.offsetWidth; r.classList.add("flash");
}

function setStatus(s){
  elStatus.textContent = s || "\u2014";
  elStatus.classList.toggle("playing", s==="PLAYING");
  elStatus.classList.toggle("menu", s==="IN MENU");
}

let frames=0, lastRateT=performance.now();
function ingest(d){
  for(const k of KEYS){
    const v = (typeof d[k]==="number") ? d[k] : 0;
    if(v !== lastSeen[k]){ flash(k); lastSeen[k]=v; }
    target[k] = v;
  }
  setStatus(d.status);
  render(); hexline();
  frames++;
  const now = performance.now();
  if(now - lastRateT >= 1000){ elRate.textContent = frames+" Hz"; frames=0; lastRateT=now; }
}

let es=null, retry=0;
function connect(){
  elDot.classList.remove("live");
  setStatus("connecting");
  try{ es && es.close(); }catch(e){}
  es = new EventSource(ENDPOINT + "/events");
  es.onopen = () => { retry=0; elDot.classList.add("live"); };
  es.onmessage = e => { elDot.classList.add("live"); try{ ingest(JSON.parse(e.data)); }catch(err){} };
  es.onerror = () => {
    elDot.classList.remove("live"); setStatus("reconnect");
    try{ es.close(); }catch(e){}
    retry = Math.min(retry+1, 6);
    setTimeout(connect, 400*retry);
  };
}
connect();

addEventListener("keydown", e=>{ if(e.key==="t"||e.key==="T") document.getElementById("theme").click(); });
</script>
</body>
</html>"""

HTML_BYTES = HTML.encode("utf-8")


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ── 页面 ──────────────────────────────────────────────
    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(HTML_BYTES)))
        self.end_headers()
        self.wfile.write(HTML_BYTES)

    # ── 流式代理 /events ──────────────────────────────────
    def _proxy_events(self):
        try:
            up = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=5)
            up.request("GET", "/events")
            resp = up.getresponse()
        except (ConnectionRefusedError, socket.error, OSError):
            # 上游没起：给浏览器一个明确的 SSE，让前端进重连逻辑
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                self.wfile.write(
                    b'data: {"critical":0,"justice":0,"attack":0,"miss":0,'
                    b'"status":"NO UPSTREAM"}\n\n')
                self.wfile.flush()
            except OSError:
                pass
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                chunk = resp.read(64)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try: up.close()
            except Exception: pass

    # ── 一次性代理 /data ──────────────────────────────────
    def _proxy_data(self):
        try:
            up = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=5)
            up.request("GET", "/data")
            resp = up.getresponse()
            body = resp.read()
        except (ConnectionRefusedError, socket.error, OSError):
            body = (b'{"critical":0,"justice":0,"attack":0,"miss":0,'
                    b'"status":"NO UPSTREAM"}')
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try: self.wfile.write(body)
        except OSError: pass

    def do_GET(self):
        if self.path == "/events":
            self._proxy_events()
        elif self.path == "/data":
            self._proxy_data()
        else:
            self._serve_html()


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    print(f"overlay 前端: http://localhost:{LISTEN_PORT}")
    print(f"代理上游:     http://{UPSTREAM_HOST}:{UPSTREAM_PORT} (chuni.py)")
    print("Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
        srv.shutdown()


if __name__ == "__main__":
    main()