"""LOCAL executor (EXECUTOR=local): compiles and runs C++ with the g++ installed on THIS machine.

Two modes:
 * Linux container (Docker on Render, run as root): every compile and run is executed as the unprivileged user 'nobody' with
   CPU / memory / file-size / process limits, a wall-clock timeout, an empty environment and a private directory.
 * Windows/laptop demo mode (needs MinGW g++ and LOCAL_EXEC_ALLOW_SAME_USER=1): runs as the SAME user with only a wall-clock
   timeout and a minimal environment. No memory/CPU limits. For a single-user laptop demo ONLY.
SECURITY: neither mode is a full sandbox (network is not blocked). Use only for a closed demo; use isolated Judge0 for exams.
Same interface as Judge0Executor."""
import hashlib, os, shutil, signal, subprocess, tempfile, threading, time
from executor import ExecutorError, MAX_OUT
try:                                  # POSIX only; absent on Windows
    import pwd, resource
except ImportError:
    pwd = resource = None

IS_WIN = os.name == "nt"
EXE = "a.exe" if IS_WIN else "a.out"
SIGNAMES = {6: "SIGABRT", 7: "SIGBUS", 8: "SIGFPE", 11: "SIGSEGV", 4: "SIGILL"}
WIN_SIGNAMES = {
    0xc0000005: "SIGSEGV",
    0xc0000094: "SIGFPE",
    0xc000001d: "SIGILL",
    0xc00000fd: "SIGSEGV",
}
if IS_WIN:
    try:
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass

class LocalExecutor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sem = threading.Semaphore(max(1, cfg.get("LOCAL_EXEC_CONCURRENCY", 1)))
        self.root = os.path.join(tempfile.gettempdir(), "codelab-run"); os.makedirs(self.root, exist_ok=True)
        if not IS_WIN: os.chmod(self.root, 0o755)
        self.lock, self.cache, self.uid = threading.Lock(), {}, None
        if pwd is not None and not IS_WIN and hasattr(os, "geteuid") and os.geteuid() == 0:
            try: self.uid = pwd.getpwnam("nobody").pw_uid
            except KeyError: self.uid = 65534
    @property
    def isolated(self): return self.uid is not None
    @property
    def configured(self):
        return shutil.which("g++") is not None and (self.isolated or bool(self.cfg.get("LOCAL_EXEC_ALLOW_SAME_USER")))
    def describe(self):
        iso = ("runs as user 'nobody' + rlimits" if self.isolated else
               "SAME USER, wall-clock timeout only (Windows laptop demo mode)" if IS_WIN else "SAME USER as the web app + rlimits (weak)")
        return {"configured": self.configured, "host": "this machine (local g++)", "language_id": "-", "auth": "none", "mode": "local", "isolation": iso}
    def _need_ready(self):
        if shutil.which("g++") is None: raise ExecutorError("not_configured", "g++ is not installed on this machine (use the Dockerfile on Render, or install MinGW on Windows).")
        if not self.configured: raise ExecutorError("not_configured", "Local execution needs root in a container (to drop privileges) or LOCAL_EXEC_ALLOW_SAME_USER=1 on a laptop.")
    def verify(self):
        self._need_ready()
        v = subprocess.run(["g++", "--version"], capture_output=True, text=True, timeout=15).stdout.splitlines()[0]
        return {"language_id": "local", "language": "C++ (" + v + ")", "cpp_languages": [v]}
    # ---- internals ----
    def _chown(self, path):
        if self.uid is not None: os.chown(path, self.uid, self.uid)
    def _limits(self, cpu, mem_bytes, nproc, fsize=1_000_000):
        def f():
            resource.setrlimit(resource.RLIMIT_CPU, (int(cpu) + 1, int(cpu) + 2))
            if mem_bytes: resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize)); resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64)); resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return f
    def _popen(self, argv, cwd, stdin, stdout, stderr, cpu, mem_bytes, nproc):
        if IS_WIN:
            env = os.environ.copy()
            env["TEMP"] = cwd
            env["TMP"] = cwd
            for attempt in range(5):
                try:
                    return subprocess.Popen(argv, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr, env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                except OSError as e:
                    if getattr(e, "winerror", None) in (4551, 5, 32) and attempt < 4:
                        time.sleep(0.05 * (2 ** attempt))
                        continue
                    raise
        kw = dict(user=self.uid, group=self.uid, extra_groups=[]) if self.uid is not None else {}
        return subprocess.Popen(argv, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True,
                                env={"PATH": "/usr/bin:/bin", "HOME": cwd, "TMPDIR": cwd, "LANG": "C.UTF-8"},
                                preexec_fn=self._limits(cpu, mem_bytes, nproc), **kw)
    @staticmethod
    def _kill(p):
        if p.poll() is not None:
            return
        if IS_WIN:
            try: subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, timeout=10)
            except Exception: pass
            try: p.kill()
            except Exception: pass
            return
        try: os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError): pass
    def _compile(self, code):
        h = hashlib.sha256(code.encode("utf-8")).hexdigest()[:24]
        with self.lock:
            e = self.cache.get(h)
            if e and os.path.exists(e["exe"]): e["t"] = time.time(); return e, None
        d = tempfile.mkdtemp(dir=self.root)
        if not IS_WIN: os.chmod(d, 0o755)
        self._chown(d); src = os.path.join(d, "main.cpp")
        with open(src, "w", encoding="utf-8") as f: f.write(code)
        if not IS_WIN: os.chmod(src, 0o644)
        ctime = self.cfg.get("LOCAL_COMPILE_TIMEOUT", 60)
        try:
            with open(os.path.join(d, "cerr.txt"), "wb") as ferr:
                p = self._popen(["g++", "-std=c++17", self.cfg.get("LOCAL_CXX_OPT", "-O1"), "-pipe", "-o", EXE, "main.cpp"], d,
                                subprocess.DEVNULL, subprocess.DEVNULL, ferr, ctime, 1_500_000_000, 128)
                try: p.wait(timeout=ctime)
                except subprocess.TimeoutExpired:
                    self._kill(p); p.wait(); raise ExecutorError("timeout", "Compilation took too long.")
                self._kill(p)
            if p.returncode != 0:
                with open(os.path.join(d, "cerr.txt"), "rb") as f: msg = f.read(8000).decode("utf-8", "replace")
                shutil.rmtree(d, ignore_errors=True)
                return None, msg.replace(d + os.sep, "").replace(d + "/", "")
        except BaseException:
            shutil.rmtree(d, ignore_errors=True); raise
        e = {"dir": d, "exe": os.path.join(d, EXE), "t": time.time()}
        with self.lock:
            self.cache[h] = e
            old = sorted(self.cache.items(), key=lambda kv: kv[1]["t"])
            while len(self.cache) > self.cfg.get("LOCAL_CACHE_SIZE", 40) or (old and time.time() - old[0][1]["t"] > 1200 and len(self.cache) > 1):
                k, v = old.pop(0); self.cache.pop(k, None); shutil.rmtree(v["dir"], ignore_errors=True)
        return e, None
    # ---- public ----
    def run(self, code, stdin="", cpu_time=None, memory_kb=None):
        self._need_ready()
        cpu = float(cpu_time or self.cfg.get("CPU_TIME_LIMIT", 2)); mem = int((memory_kb or self.cfg.get("MEMORY_LIMIT_KB", 128000)) * 1024)
        if not self.sem.acquire(timeout=120): raise ExecutorError("queue_full", "The server is busy running other programs; try again.")
        try:
            e, cerr = self._compile(code)
            if e is None:
                return {"kind": "compile_error", "status": "Compilation Error", "status_id": 6, "stdout": "", "stderr": "", "compile_output": cerr,
                        "time": None, "memory": None, "message": ""}
            rd = tempfile.mkdtemp(dir=e["dir"])
            if not IS_WIN: os.chmod(rd, 0o755)
            self._chown(rd)
            try:
                paths = {k: os.path.join(rd, k) for k in ("in", "out", "err")}
                with open(paths["in"], "wb") as f: f.write((stdin or "").encode("utf-8"))
                with open(paths["in"], "rb") as fin, open(paths["out"], "wb") as fout, open(paths["err"], "wb") as ferr:
                    t0 = time.monotonic(); p = self._popen([e["exe"]], rd, fin, fout, ferr, cpu, mem, 64); timed_out = False
                    try: p.wait(timeout=cpu * 2 + 1)
                    except subprocess.TimeoutExpired: timed_out = True; self._kill(p); p.wait()
                    self._kill(p); dt = time.monotonic() - t0
                with open(paths["out"], "rb") as f: out = f.read(MAX_OUT).decode("utf-8", "replace")
                with open(paths["err"], "rb") as f: err = f.read(20000).decode("utf-8", "replace")
            finally:
                shutil.rmtree(rd, ignore_errors=True)
            rc = p.returncode; r = {"stdout": out, "stderr": err, "compile_output": "", "time": round(dt, 3), "memory": None, "message": ""}
            if timed_out or rc in (-24,) or (rc == -9 and dt >= cpu * 0.9): return dict(r, kind="timeout", status="Time Limit Exceeded", status_id=5)
            if rc == 0: return dict(r, kind="ok", status="Accepted", status_id=3)
            if "bad_alloc" in err: return dict(r, kind="memory_limit", status="Memory Limit Exceeded", status_id=7)
            if IS_WIN:
                u_rc = rc & 0xffffffff
                sig = WIN_SIGNAMES.get(u_rc)
                name = f"Runtime Error ({sig})" if sig else "Runtime Error (NZEC)"
                return dict(r, kind="runtime_error", status=name, status_id=7 if sig else 11)
            sig = -rc if rc < 0 else None
            name = f"Runtime Error ({SIGNAMES.get(sig, 'signal ' + str(sig))})" if sig else "Runtime Error (NZEC)"
            return dict(r, kind="runtime_error", status=name, status_id=11 if sig is None else 7)
        finally:
            self.sem.release()
