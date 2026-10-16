import os, re, tempfile, threading, time
from app import create_app
from executor import ExecutorError

HIDDEN_INPUT, HIDDEN_EXPECTED = "1000000000 1000000000", "2000000000"   # seeded hidden test of 'Sum of Two Numbers'

class ScriptedExecutor:
    """MOCK executor (no compiler!). Behaviour is driven by markers in the code. Used only for unit tests of our own logic."""
    configured = True
    def __init__(self): self.calls, self.fail_after, self.gate = 0, None, None
    def describe(self): return {"configured": True}
    def run(self, code, stdin="", cpu_time=None, memory_kb=None):
        self.calls += 1
        if self.gate: self.gate.wait(5)
        if "SERVICE_DOWN" in code or (self.fail_after is not None and self.calls > self.fail_after):
            raise ExecutorError("network", "Could not reach the execution service.")
        if "COMPILE_FAIL" in code:
            return dict(kind="compile_error", status="Compilation Error", stdout="", stderr="", compile_output="error: expected expression", time=None, memory=None, message="")
        if "RUNTIME_FAIL" in code:
            return dict(kind="runtime_error", status="Runtime Error (SIGSEGV)", stdout="", stderr="segfault", compile_output="", time=0.01, memory=100, message="")
        nums = [int(x) for x in stdin.split()]
        out = "0" if "WRONG" in code else str(sum(nums))
        if "TRAILING" in code: out += "   \r\n\r\n"
        return dict(kind="ok", status="Accepted", stdout=out + ("\n" if "TRAILING" not in code else ""), stderr="", compile_output="", time=0.01, memory=100, message="")
    def verify(self): return {"language": "mock"}

def make_app(executor=None, **cfg):
    d = tempfile.mkdtemp()
    base = {"DATABASE_URL": "sqlite:///" + os.path.join(d, "t.db"), "EVAL_SYNC": True, "SECRET_KEY": "test-secret", "APP_ENV": "testing"}
    base.update(cfg)
    app = create_app(base, executor=executor if executor is not None else ScriptedExecutor())
    return app, d

def csrf_from(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if m: return m.group(1)
    with client.session_transaction() as s: return s["csrf"]

def login(client, user, pw):
    t = csrf_from(client, "/login")
    return client.post("/login", data={"username": user, "password": pw, "csrf_token": t})

def hdr(client):
    with client.session_transaction() as s: return {"X-CSRF-Token": s["csrf"]}

def student(app, who="student01"):
    c = app.test_client(); login(c, who, {"student01": "Student@123", "student02": "Student@456"}[who]); return c
def teacher(app):
    c = app.test_client(); login(c, "teacher01", "Teacher@123"); return c

def submit(client, aid, code, token=None):
    import uuid
    return client.post(f"/api/assignments/{aid}/submit", json={"code": code, "client_token": token or uuid.uuid4().hex}, headers=hdr(client))

def wait_terminal(client, sid, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/submissions/{sid}").get_json()
        if r["status"] in ("evaluated_passed", "evaluated_failed", "evaluation_error"): return r
        time.sleep(0.05)
    raise AssertionError("evaluation did not finish")
