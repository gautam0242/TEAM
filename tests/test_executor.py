"""Executor adapter tests. They talk HTTP to tests/fake_judge0.py - a Judge0-PROTOCOL test double that compiles with local g++.
This verifies OUR adapter (tokens, polling, base64, retries, error mapping). It does NOT verify real Judge0."""
import unittest
from config import load_config
from executor import Judge0Executor, ExecutorError
from tests import fake_judge0

def make(srv, **o):
    base = dict(JUDGE0_URL=srv.url, JUDGE0_POLL_INTERVAL=0.01, JUDGE0_MAX_RETRIES=2, JUDGE0_DEADLINE=20, SECRET_KEY="x"); base.update(o)
    cfg = load_config(base)
    return Judge0Executor(cfg, sleep=lambda s: None)

class ExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.srv = fake_judge0.start()
    def setUp(self): self.srv.fault, self.srv.fault_used, self.srv.requests = None, False, 0
    def test_hello_and_polling(self):
        r = make(self.srv).run('#include <iostream>\nint main(){std::cout<<"hi";}')
        self.assertEqual((r["kind"], r["stdout"], r["status_id"]), ("ok", "hi", 3)); self.assertGreaterEqual(self.srv.requests, 3)   # POST + >=2 polls (first poll says 'Processing')
    def test_wait_mode_uses_one_request(self):
        r = make(self.srv, JUDGE0_USE_WAIT=True).run('#include <iostream>\nint main(){std::cout<<"w";}'); self.assertEqual((r["stdout"], self.srv.requests), ("w", 1))
    def test_wait_not_allowed_falls_back_to_polling(self):
        self.srv.fault = "no_wait"; r = make(self.srv, JUDGE0_USE_WAIT=True).run('#include <iostream>\nint main(){std::cout<<"f";}'); self.assertEqual(r["stdout"], "f"); self.assertGreaterEqual(self.srv.requests, 3)
    def test_stdin_and_unicode(self):
        r = make(self.srv).run('#include <iostream>\n#include <string>\nint main(){std::string s; std::getline(std::cin,s); std::cout<<s;}', "héllo wörld ✓")
        self.assertEqual(r["stdout"], "héllo wörld ✓")
    def test_compile_error(self):
        r = make(self.srv).run("int main(){ int x = ; }")
        self.assertEqual((r["kind"], r["status_id"]), ("compile_error", 6)); self.assertIn("error", r["compile_output"])
    def test_runtime_error(self):
        r = make(self.srv).run("int main(){ int *p=nullptr; return *p; }"); self.assertEqual(r["kind"], "runtime_error")
    def test_timeout(self):
        r = make(self.srv).run("int main(){ volatile unsigned long long x=0; while(true) x++; }", cpu_time=1); self.assertEqual(r["kind"], "timeout")
    def test_memory_limit_detected(self):
        r = make(self.srv).run("#include <vector>\nint main(){ std::vector<char> v(900000000); v[5]=1; return v[5]; }", memory_kb=64000)
        self.assertIn(r["kind"], ("memory_limit", "runtime_error"))     # service reports a generic runtime error; we classify bad_alloc as memory_limit
    def test_verify_language(self):
        v = make(self.srv).verify(); self.assertEqual(v["language_id"], 54); self.assertIn("C++", v["language"])
        with self.assertRaises(ExecutorError) as e: make(self.srv, JUDGE0_LANGUAGE_ID=999).verify()
        self.assertEqual(e.exception.kind, "bad_request"); self.assertIn("54", e.exception.message)
    def test_faults(self):
        for fault, kind in (("auth", "auth"), ("malformed", "malformed"), ("garbage_token", "malformed"), ("internal", "internal"), ("503", "internal"), ("queue_full", "queue_full")):
            self.srv.fault = fault
            with self.assertRaises(ExecutorError, msg=fault) as e: make(self.srv).run("int main(){}")
            self.assertEqual(e.exception.kind, kind, fault)
    def test_rate_limit_recovers_with_retry(self):
        self.srv.fault = "429_once"; r = make(self.srv).run("int main(){}"); self.assertEqual(r["kind"], "ok")
    def test_retries_are_bounded_and_back_off(self):
        sleeps = []; self.srv.fault = "503"; ex = make(self.srv); ex.sleep = sleeps.append
        with self.assertRaises(ExecutorError): ex.run("int main(){}")
        self.assertEqual(self.srv.requests, 3); self.assertEqual(len(sleeps), 2); self.assertLess(sleeps[0], sleeps[1])
    def test_deadline(self):
        self.srv.fault = "slow"; t = [0.0]; ex = make(self.srv, JUDGE0_DEADLINE=5); ex.clock = lambda: t[0]; ex.sleep = lambda s: t.__setitem__(0, t[0] + 1.5)
        with self.assertRaises(ExecutorError) as e: ex.run("int main(){}")
        self.assertEqual(e.exception.kind, "timeout")
    def test_unreachable_and_not_configured(self):
        cfg = load_config(dict(JUDGE0_URL="http://127.0.0.1:9", JUDGE0_MAX_RETRIES=1, JUDGE0_HTTP_TIMEOUT=1, SECRET_KEY="x"))
        with self.assertRaises(ExecutorError) as e: Judge0Executor(cfg, sleep=lambda s: None).run("int main(){}")
        self.assertEqual(e.exception.kind, "network")
        with self.assertRaises(ExecutorError) as e: Judge0Executor(load_config(dict(JUDGE0_URL="", SECRET_KEY="x"))).run("x")
        self.assertEqual(e.exception.kind, "not_configured")
    def test_api_key_header_sent_and_never_leaked(self):
        srv = fake_judge0.start(api_key="s3cret-key")
        ok = make(srv, JUDGE0_API_KEY="s3cret-key").run("int main(){}"); self.assertEqual(ok["kind"], "ok")
        bad = make(srv, JUDGE0_API_KEY="wrong")
        with self.assertRaises(ExecutorError) as e: bad.run("int main(){}")
        self.assertEqual(e.exception.kind, "auth"); self.assertNotIn("wrong", e.exception.message)
        d = make(srv, JUDGE0_API_KEY="s3cret-key").describe(); self.assertNotIn("s3cret-key", str(d))
    def test_rapidapi_headers(self):
        ex = make(self.srv, JUDGE0_API_KEY="k", JUDGE0_API_HOST="judge0-ce.p.rapidapi.com"); h = ex._headers()
        self.assertEqual((h["X-RapidAPI-Key"], h["X-RapidAPI-Host"]), ("k", "judge0-ce.p.rapidapi.com"))

class EndToEndWithDouble(unittest.TestCase):
    """Whole Flask app + real adapter + g++-backed test double: submit real C++ and get real compiler-judged verdicts."""
    def test_real_compile_flow(self):
        from tests.helpers import make_app, student, submit, wait_terminal, hdr
        srv = fake_judge0.start(); ex = make(srv); app, _ = make_app(ex); s = student(app)
        good = "#include <iostream>\nint main(){ long long a,b; std::cin>>a>>b; std::cout<<a+b; }"
        res = wait_terminal(s, submit(s, 1, good).get_json()["submission_id"], 60); self.assertEqual((res["status"], res["passed_count"]), ("evaluated_passed", 4))
        bad = wait_terminal(s, submit(s, 1, "#include <iostream>\nint main(){ long long a,b; std::cin>>a>>b; std::cout<<a-b; }").get_json()["submission_id"], 60)
        self.assertEqual(bad["status"], "evaluated_failed")
        ce = wait_terminal(s, submit(s, 1, "int main(){ int x = ; }").get_json()["submission_id"], 60); self.assertEqual(ce["status"], "evaluated_failed"); self.assertTrue(ce["compile_output"])
        srv.fault = "503"
        down = wait_terminal(s, submit(s, 1, good).get_json()["submission_id"], 60); self.assertEqual(down["status"], "evaluation_error")   # service outage != wrong answer
        r = s.post("/api/assignments/1/run", json={"code": good, "stdin": "1 2"}, headers=hdr(s)); self.assertEqual(r.status_code, 503)
        srv.fault = None
        r = s.post("/api/assignments/1/run", json={"code": good, "stdin": "20 22"}, headers=hdr(s)); self.assertEqual(r.get_json()["stdout"], "42")

if __name__ == "__main__": unittest.main()
