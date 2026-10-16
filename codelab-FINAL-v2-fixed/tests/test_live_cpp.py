"""C++ compatibility suite. Runs ONLY when a real service is configured (JUDGE0_URL) or LIVE_TEST_DOUBLE=1 (harness self-check against the
g++-backed test double). Expected outputs in expected_outputs.json were produced by LOCAL g++ and are compared with the configured service."""
import json, os, unittest
from config import load_config
from executor import Judge0Executor

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "expected_outputs.json"), "r", encoding="utf-8") as f:
    REF = json.load(f)
def _executor():
    if os.getenv("LIVE_TEST_DOUBLE") == "1":
        from tests import fake_judge0
        srv = fake_judge0.start(); return Judge0Executor(load_config(dict(JUDGE0_URL=srv.url, JUDGE0_POLL_INTERVAL=0.05, SECRET_KEY="x"))), "TEST DOUBLE (local g++)"
    if os.getenv("JUDGE0_URL"): return Judge0Executor(load_config(dict(SECRET_KEY="x"))), os.getenv("JUDGE0_URL")
    return None, ""
EX, WHERE = _executor()

@unittest.skipIf(EX is None, "set JUDGE0_URL (and key) or LIVE_TEST_DOUBLE=1 to run")
class CppSuite(unittest.TestCase):
    def src(self, n):
        with open(os.path.join(HERE, "cpp_programs", n + ".cpp"), "r", encoding="utf-8") as f:
            return f.read()
    def test_service_language(self):
        v = EX.verify(); print(f"\n[live] service={WHERE} language={v['language']} (reference g++: {REF['_compiler']})")
    def test_programs_match_local_gpp(self):
        for n, ref in REF.items():
            if n.startswith("_") or "stdout" not in ref: continue
            with self.subTest(program=n):
                r = EX.run(self.src(n), ref["stdin"]); self.assertEqual(r["kind"], "ok", r.get("compile_output")); self.assertEqual(r["stdout"], ref["stdout"])
    def test_error_kinds(self):
        self.assertEqual(EX.run(self.src("compile_error"))["kind"], "compile_error")
        self.assertEqual(EX.run(self.src("runtime_error"))["kind"], "runtime_error")
        self.assertEqual(EX.run(self.src("timeout"), cpu_time=1)["kind"], "timeout")
if __name__ == "__main__": unittest.main()
