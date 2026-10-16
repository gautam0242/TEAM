"""TEST DOUBLE speaking the Judge0 HTTP protocol (token + polling, base64) and compiling with the LOCAL g++.
It is NOT real Judge0 and NOT sandboxed (only ulimit-style limits). For automated tests only - never expose it to students.
Fault injection: set server.fault to one of: None, '429_once', '503', 'auth', 'malformed', 'queue_full', 'garbage_token', 'slow', 'internal'."""
import base64, json, os, subprocess, tempfile, threading, uuid
try:
    import resource
except ImportError:
    resource = None
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IS_WIN = os.name == "nt"
EXE = "a.exe" if IS_WIN else "a.out"
if IS_WIN:
    try:
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass

def _limits(mem_kb, cpu):
    if resource is None:
        return None
    def f():
        resource.setrlimit(resource.RLIMIT_AS, (mem_kb * 1024, mem_kb * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (int(cpu) + 1, int(cpu) + 1))
    return f

def run_cpp(source, stdin, cpu=2.0, mem_kb=256000):
    d = tempfile.mkdtemp(); src, exe = os.path.join(d, "a.cpp"), os.path.join(d, EXE)
    with open(src, "w", encoding="utf-8") as f: f.write(source)
    c = subprocess.run(["g++", "-std=c++17", "-O2", "-o", exe, src], capture_output=True, text=True, timeout=60)
    if c.returncode != 0: return dict(status={"id": 6, "description": "Compilation Error"}, compile_output=c.stderr, stdout=None, stderr=None, time=None, memory=None)
    try:
        lim = _limits(mem_kb, cpu)
        kw = dict(preexec_fn=lim) if lim else {}
        for attempt in range(5):
            try:
                p = subprocess.run([exe], input=stdin, capture_output=True, encoding="utf-8", errors="replace", timeout=cpu + 1, **kw)
                break
            except OSError as e:
                if IS_WIN and getattr(e, "winerror", None) in (4551, 5, 32) and attempt < 4:
                    import time; time.sleep(0.05 * (2 ** attempt))
                    continue
                raise
    except subprocess.TimeoutExpired:
        return dict(status={"id": 5, "description": "Time Limit Exceeded"}, stdout="", stderr="", compile_output=None, time=str(cpu), memory=1000)
    rc = p.returncode
    if rc == 0:
        sid, desc = 3, "Accepted"
    elif IS_WIN:
        u_rc = rc & 0xffffffff
        if u_rc == 0xc0000005: sid, desc = 7, "Runtime Error (SIGSEGV)"
        elif u_rc == 0xc0000094: sid, desc = 9, "Runtime Error (SIGFPE)"
        elif u_rc == 0xc000001d: sid, desc = 7, "Runtime Error (SIGILL)"
        else: sid, desc = 11, "Runtime Error (NZEC)"
    else:
        sid, desc = (7, "Runtime Error (SIGSEGV)") if rc == -11 else (9, "Runtime Error (SIGFPE)") if rc == -8 else (10, "Runtime Error (SIGABRT)") if rc == -6 else (11, "Runtime Error (NZEC)")
    return dict(status={"id": sid, "description": desc}, stdout=p.stdout, stderr=p.stderr, compile_output=None, time="0.01", memory=1500)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def _fault(self):
        srv, f = self.server, self.server.fault
        srv.requests += 1
        if srv.api_key and self.headers.get("X-Auth-Token") != srv.api_key and f != "auth": return self._send(403, {"error": "forbidden"}) or True
        if f == "auth": return self._send(403, {"error": "forbidden"}) or True
        if f == "503": return self._send(503, {"error": "unavailable"}) or True
        if f == "queue_full": return self._send(503, {"error": "queue is full"}) or True
        if f == "internal": return self._send(500, {"error": "boom"}) or True
        if f == "malformed": return self._send(200, None, raw=b"<html>not json</html>") or True
        if f == "429_once" and not srv.fault_used: srv.fault_used = True; return self._send(429, {"error": "slow down"}) or True
        return False
    def do_GET(self):
        if self._fault(): return
        if self.path.startswith("/languages"): return self._send(200, [{"id": 54, "name": "C++ (GCC 9.2.0)"}, {"id": 52, "name": "C++ (GCC 7.4.0)"}, {"id": 71, "name": "Python (3.8.1)"}])
        if self.path.startswith("/submissions/"):
            tok = self.path.split("/")[2].split("?")[0]; job = self.server.jobs.get(tok)
            if not job: return self._send(404, {"error": "not found"})
            job["polls"] += 1
            if job["polls"] == 1 or self.server.fault == "slow": return self._send(200, {"status": {"id": 2, "description": "Processing"}})
            r = job["result"]; b = lambda x: None if x is None else base64.b64encode(x.encode("utf-8")).decode()
            return self._send(200, dict(status=r["status"], stdout=b(r["stdout"]), stderr=b(r["stderr"]), compile_output=b(r["compile_output"]), time=r["time"], memory=r["memory"], message=None))
        self._send(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n > 0 else b""
        if self._fault(): return
        d = json.loads(raw.decode("utf-8"))
        if self.server.fault == "garbage_token": return self._send(200, {"nothing": 1})
        dec = lambda s: base64.b64decode(s).decode("utf-8")
        res = run_cpp(dec(d["source_code"]), dec(d.get("stdin", "")), d.get("cpu_time_limit", 2), d.get("memory_limit", 256000))
        if "wait=true" in self.path:
            if self.server.fault == "no_wait": return self._send(400, {"error": "wait is not allowed"})
            b = lambda x: None if x is None else base64.b64encode(x.encode("utf-8")).decode()
            return self._send(201, dict(status=res["status"], stdout=b(res["stdout"]), stderr=b(res["stderr"]), compile_output=b(res["compile_output"]), time=res["time"], memory=res["memory"], message=None))
        tok = uuid.uuid4().hex; self.server.jobs[tok] = {"polls": 0, "result": res}; self._send(201, {"token": tok})

def start(api_key=None):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.fault, srv.fault_used, srv.jobs, srv.requests, srv.api_key = None, False, {}, 0, api_key
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"; return srv
