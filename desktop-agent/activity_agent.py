"""Privacy-scoped, offline-resilient desktop activity agent.

Only coarse activity state and a coarse application category are collected.
No keystrokes, screenshots, window titles, URLs, source code, documents,
terminal commands/output, or clipboard contents are collected or transmitted.

The agent keeps a small SQLite queue locally. Network loss therefore does not
become employee inactivity: activity events are queued and uploaded when the
server is reachable again. Connectivity gaps are sent separately so the
server can distinguish monitoring-unavailable time from inactivity.
"""
from __future__ import annotations
import json, os, platform, sqlite3, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request, error
try:
    import psutil
except ImportError:
    psutil = None

HOST = "127.0.0.1"
PORT = int(os.environ.get("ATTENDANCE_AGENT_PORT", "17891"))
HEARTBEAT_SECONDS = max(15, int(os.environ.get("ATTENDANCE_AGENT_HEARTBEAT_SECONDS", "30")))
IDLE_LIMIT_SECONDS = max(60, int(os.environ.get("ATTENDANCE_AGENT_IDLE_LIMIT_SECONDS", "600")))
MAX_QUEUE_ROWS = 10_000
CONFIG_DIR = Path.home() / ".attendance-activity-agent"
CONFIG_FILE = CONFIG_DIR / "config.json"
DB_FILE = CONFIG_DIR / "agent_queue.sqlite3"

state = {
    "api_base_url": None,
    "token": None,
    "token_expires_at": 0.0,
    "last_error": None,
    "last_heartbeat_at": None,
    "last_app_category": None,
    "offline_started_at": None,
    "running": True,
}
lock = threading.Lock()

def db():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_FILE, timeout=5)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("""CREATE TABLE IF NOT EXISTS queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at REAL NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_queue_id ON queue(id)")
    c.commit()
    return c

def queue_event(event_type, payload):
    c = db()
    try:
        c.execute("INSERT INTO queue(event_type,payload,created_at) VALUES(?,?,?)", (event_type, json.dumps(payload, separators=(",", ":")), time.time()))
        # Bound local storage. Oldest events are discarded only after a very large
        # backlog; this prevents an unattended laptop from growing without limit.
        c.execute("DELETE FROM queue WHERE id IN (SELECT id FROM queue ORDER BY id DESC LIMIT -1 OFFSET ?)", (MAX_QUEUE_ROWS,))
        c.commit()
    finally:
        c.close()

def peek_events(limit=100):
    c = db()
    try:
        return c.execute("SELECT id,event_type,payload FROM queue ORDER BY id LIMIT ?", (limit,)).fetchall()
    finally:
        c.close()

def delete_event(row_id):
    c = db()
    try:
        c.execute("DELETE FROM queue WHERE id=?", (row_id,)); c.commit()
    finally:
        c.close()

def queue_size():
    c = db()
    try: return c.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
    finally: c.close()

def load_config():
    try:
        if CONFIG_FILE.exists():
            d = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            state["api_base_url"] = (d.get("api_base_url") or "").rstrip("/") or None
    except Exception:
        pass

def save_config(url):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"api_base_url": url.rstrip("/")}), encoding="utf-8")

def windows_idle_seconds():
    if platform.system() != "Windows": return None
    import ctypes
    class LI(ctypes.Structure): _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    x = LI(); x.cbSize = ctypes.sizeof(x)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(x)): return None
    return max(0, (ctypes.windll.kernel32.GetTickCount64() - x.dwTime) / 1000)

def linux_idle_seconds():
    for c in (["xprintidle"], ["xssstate", "-i"]):
        try:
            v = float(subprocess.check_output(c, stderr=subprocess.DEVNULL, timeout=1).decode().strip())
            return v / 1000 if c[0] == "xprintidle" else v
        except Exception: pass
    return None

def mac_idle_seconds():
    try:
        o = subprocess.check_output(["ioreg", "-c", "IOHIDSystem"], stderr=subprocess.DEVNULL, timeout=1).decode(errors="ignore")
        p = o.find("HIDIdleTime")
        return int(o[p:].split("=", 1)[1].split("\n", 1)[0].strip()) / 1e9 if p >= 0 else None
    except Exception: return None

def idle_seconds():
    return windows_idle_seconds() if platform.system()=="Windows" else mac_idle_seconds() if platform.system()=="Darwin" else linux_idle_seconds()

def foreground_process_name():
    try:
        if platform.system() == "Windows":
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow(); pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return psutil.Process(pid.value).name() if psutil else None
        if platform.system() == "Darwin":
            return subprocess.check_output(["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'], stderr=subprocess.DEVNULL, timeout=1).decode().strip()
        wid = subprocess.check_output(["xdotool", "getactivewindow"], stderr=subprocess.DEVNULL, timeout=1).decode().strip()
        return subprocess.check_output(["xdotool", "getwindowpid", wid], stderr=subprocess.DEVNULL, timeout=1).decode().strip()
    except Exception: return None

WORK_PROCESS_CATEGORIES = {
    "code":"development","code-insiders":"development","cursor":"development","pycharm":"development","idea":"development","webstorm":"development","clion":"development","rider":"development","eclipse":"development","devenv":"development","android studio":"development","xcode":"development",
    "powershell":"terminal","pwsh":"terminal","cmd":"terminal","windowsterminal":"terminal","wt":"terminal","bash":"terminal","zsh":"terminal","fish":"terminal","terminal":"terminal",
    "postman":"api_testing","insomnia":"api_testing","dbeaver":"database","pgadmin":"database","datagrip":"database","mysqlworkbench":"database","ssms":"database",
    "githubdesktop":"version_control","sourcetree":"version_control","gitkraken":"version_control","excel":"office","winword":"office","powerpnt":"office","libreoffice":"office","soffice":"office","figma":"design","photoshop":"design","illustrator":"design","teams":"communication","slack":"communication","zoom":"communication","outlook":"communication",
}
NON_WORK_PROCESS_NAMES = {"steam","steamwebhelper","spotify","solitaire","epicgameslauncher","robloxplayerbeta","discord","battle.net","leagueclient"}
BROWSER_NAMES = {"chrome","msedge","firefox","brave","opera","vivaldi","safari"}

def app_category(name):
    stem = Path((name or "").lower()).stem
    if stem in BROWSER_NAMES: return "browser"
    if stem in NON_WORK_PROCESS_NAMES: return "non_work"
    for k,v in WORK_PROCESS_CATEGORIES.items():
        if k in stem: return v
    return "other_desktop"

def post_json(path, payload):
    base = state.get("api_base_url"); token = state.get("token")
    if not base or not token or time.time() >= state.get("token_expires_at", 0): return False, "agent token unavailable or expired"
    req = request.Request(f"{base}{path}", data=json.dumps(payload).encode(), headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=8) as r: return 200 <= r.status < 300, r.read().decode(errors="ignore")
    except error.HTTPError as e: return False, f"HTTP {e.code}"
    except Exception as e: return False, str(e)

def local_iso(ts):
    return time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(ts))

def upload_queue():
    # Upload in order. If the first item fails, stop; preserving ordering makes
    # reconstruction of activity and connectivity periods deterministic.
    for row_id, event_type, raw in peek_events(100):
        try: payload = json.loads(raw)
        except Exception:
            delete_event(row_id); continue
        ok, err = post_json("/api/activity/desktop-event", payload)
        if not ok:
            return False, err
        delete_event(row_id)
    return True, None

def activity_loop():
    load_config(); db().close()
    while state["running"]:
        time.sleep(HEARTBEAT_SECONDS)
        with lock: token = state.get("token")
        if not token: continue
        now = time.time(); idle = idle_seconds()
        # A ping checks connectivity/authorization without creating an
        # activity heartbeat. This lets us distinguish network loss from
        # genuine user inactivity even while the user is idle.
        ping_ok, ping_err = post_json("/api/activity/agent-ping", {})
        if not ping_ok:
            if not state.get("offline_started_at"):
                state["offline_started_at"] = now
            state["last_error"] = ping_err or "Monitoring server/network unavailable"
            continue
        if state.get("offline_started_at"):
            offline = state["offline_started_at"]
            state["offline_started_at"] = None
            queue_event("monitoring_unavailable", {"event_type":"monitoring_unavailable","started_at":local_iso(offline),"ended_at":local_iso(now)})
        if idle is not None and idle >= IDLE_LIMIT_SECONDS:
            upload_queue()
            continue
        category = app_category(foreground_process_name())
        if category == "non_work":
            upload_queue(); continue
        event_at = local_iso(now)
        queue_event("active", {"event_type":"active","event_at":event_at,"app_category":category})
        ok, err = upload_queue()
        if ok:
            state["last_heartbeat_at"] = event_at; state["last_app_category"] = category; state["last_error"] = None
        else:
            if not state.get("offline_started_at"): state["offline_started_at"] = now
            state["last_error"] = err or "Monitoring server/network unavailable"

def _json_response(handler, code, payload):
    raw=json.dumps(payload).encode(); handler.send_response(code); handler.send_header("Content-Type","application/json"); handler.send_header("Content-Length",str(len(raw))); handler.send_header("Cache-Control","no-store"); handler.end_headers(); handler.wfile.write(raw)

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self): self.send_response(204); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.end_headers()
    def do_GET(self):
        if self.path == "/status":
            with lock:
                _json_response(self,200,{"running":True,"authorized":bool(state.get("token") and time.time()<state.get("token_expires_at",0)),"last_heartbeat_at":state.get("last_heartbeat_at"),"last_app_category":state.get("last_app_category"),"last_error":state.get("last_error"),"monitoring_unavailable":bool(state.get("offline_started_at")),"queued_events":queue_size()})
        else: _json_response(self,404,{"detail":"Not found"})
    def do_POST(self):
        try: body=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}")
        except Exception: body={}
        if self.path == "/session":
            url=str(body.get("api_base_url") or "").rstrip("/"); token=body.get("token"); exp=min(900,max(60,int(body.get("expires_in") or 900)))
            if not url or not token:
                state["token"]=None; state["token_expires_at"]=0; _json_response(self,200,{"authorized":False}); return
            save_config(url); state.update({"api_base_url":url,"token":token,"token_expires_at":time.time()+exp,"last_error":None}); _json_response(self,200,{"authorized":True,"expires_in":exp}); return
        if self.path == "/stop":
            state["token"]=None; state["token_expires_at"]=0; state["offline_started_at"]=None; _json_response(self,200,{"authorized":False}); return
        _json_response(self,404,{"detail":"Not found"})
    def log_message(self,*a): return

def main():
    db().close(); server=ThreadingHTTPServer((HOST,PORT),Handler); threading.Thread(target=activity_loop,daemon=True).start(); print(f"Attendance desktop activity agent listening on http://{HOST}:{PORT}"); server.serve_forever()
if __name__ == "__main__": main()
