"""Tests of LocalExecutor against the REAL g++ installed in this environment (no test double, no mock)."""
import os, shutil, unittest
from config import load_config
from executor import ExecutorError
from local_executor import LocalExecutor

NEED = shutil.which("g++") is not None
ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
def make(**o):
    base = dict(SECRET_KEY="x", LOCAL_EXEC_ALLOW_SAME_USER=not ROOT); base.update(o); return LocalExecutor(load_config(base))

@unittest.skipUnless(NEED, "g++ not installed")
class LocalExec(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.ex = make()
    def test_hello_stdin_unicode(self):
        r = self.ex.run('#include <iostream>\n#include <string>\nint main(){std::string s;std::getline(std::cin,s);std::cout<<"Hi "<<s;}', "héllo ✓")
        self.assertEqual((r["kind"], r["stdout"], r["status_id"]), ("ok", "Hi héllo ✓", 3))
    def test_compile_error_text_has_no_server_paths(self):
        r = self.ex.run("int main(){ int x = ; }"); self.assertEqual(r["kind"], "compile_error"); self.assertIn("error", r["compile_output"]); self.assertNotIn("/tmp/", r["compile_output"])
    def test_runtime_errors(self):
        self.assertEqual(self.ex.run("int main(){ int *p=nullptr; return *p; }")["kind"], "runtime_error")
        r = self.ex.run("#include <iostream>\nint main(){ int a=0; std::cout<<5/a; }"); self.assertEqual(r["kind"], "runtime_error"); self.assertIn("SIGFPE", r["status"])
        r = self.ex.run("int main(){ return 3; }"); self.assertEqual((r["kind"], r["status"]), ("runtime_error", "Runtime Error (NZEC)"))
    def test_timeout_cpu_and_sleep(self):
        r = self.ex.run("int main(){ volatile unsigned long long x=0; while(true) x++; }", cpu_time=1); self.assertEqual(r["kind"], "timeout")
        sleep_code = "#include <windows.h>\nint main(){ Sleep(30000); }" if os.name == "nt" else "#include <unistd.h>\nint main(){ sleep(30); }"
        r = self.ex.run(sleep_code, cpu_time=1); self.assertEqual(r["kind"], "timeout")
    def test_memory_limit(self):
        r = self.ex.run("#include <vector>\nint main(){ std::vector<char> v(900000000); v[5]=1; return v[5]; }", memory_kb=64000)
        self.assertIn(r["kind"], ("memory_limit", "runtime_error")); self.assertNotEqual(r["kind"], "ok")
    def test_output_flood_is_capped(self):
        r = self.ex.run('#include <iostream>\nint main(){ while(true) std::cout<<"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n"; }', cpu_time=1)
        self.assertIn(r["kind"], ("runtime_error", "timeout")); self.assertLessEqual(len(r["stdout"]), 100000)
    @unittest.skipIf(os.name == "nt", "fork() and ps are Unix-specific")
    def test_fork_bomb_contained(self):
        r = self.ex.run('#include <unistd.h>\n#include <iostream>\nint main(){ int n=0; for(int i=0;i<500;i++){ if(fork()==0){ pause(); _exit(0);} else n++; } std::cout<<"done"; }', cpu_time=1)
        self.assertIn(r["kind"], ("ok", "runtime_error", "timeout"))
        import subprocess, time; time.sleep(0.3)   # killed children may stay as zombies (state Z) until an init process reaps them (tini in the Dockerfile); none may be ALIVE
        alive = subprocess.run("ps -eo stat,comm | awk '$2==\"a.out\" && $1 !~ /^Z/'", shell=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(alive, "")
    def test_compile_cache_reuse(self):
        code = "#include <iostream>\nint main(){std::cout<<7;}"; self.ex.run(code); n = len(self.ex.cache); self.ex.run(code); self.assertEqual(len(self.ex.cache), n)
    def test_run_directories_cleaned(self):
        code = "#include <iostream>\nint main(){std::cout<<1;}"; self.ex.run(code)
        e = next(iter(self.ex.cache.values())); leftovers = [x for x in os.listdir(e["dir"]) if os.path.isdir(os.path.join(e["dir"], x))]; self.assertEqual(leftovers, [])
    @unittest.skipUnless(ROOT, "needs root to test privilege dropping")
    def test_runs_as_unprivileged_user_and_cannot_see_secrets(self):
        os.environ["CODELAB_TEST_SECRET"] = "TOPSECRET123"
        try:
            r = self.ex.run('#include <iostream>\n#include <cstdlib>\n#include <unistd.h>\n#include <fstream>\n#include <string>\n'
                            'int main(){ std::cout<<"uid="<<getuid()<<" env="<<(getenv("CODELAB_TEST_SECRET")?"LEAK":"none");'
                            ' std::ifstream f("/proc/" + std::to_string(getppid()) + "/environ"); std::cout<<" parentenv="<<(f.good()?"READABLE":"denied"); }')
        finally: os.environ.pop("CODELAB_TEST_SECRET")
        self.assertEqual(r["stdout"], f"uid={self.ex.uid} env=none parentenv=denied"); self.assertNotEqual(self.ex.uid, 0)
    @unittest.skipUnless(ROOT, "needs root")
    def test_cannot_read_root_only_files_or_incbin_them(self):
        open("/root/codelab_secret.txt", "w").write("ROOTSECRET"); os.chmod("/root/codelab_secret.txt", 0o600)
        try:
            r = self.ex.run('#include <iostream>\n#include <fstream>\nint main(){ std::ifstream f("/root/codelab_secret.txt"); std::cout<<(f.good()?"READ":"denied"); }'); self.assertEqual(r["stdout"], "denied")
            r = self.ex.run('asm(".incbin \\"/root/codelab_secret.txt\\"");\nint main(){}'); self.assertEqual(r["kind"], "compile_error")      # compiler also runs unprivileged
        finally: os.remove("/root/codelab_secret.txt")
    def test_verify_and_describe(self):
        self.assertIn("g++", self.ex.verify()["language"]); self.assertEqual(self.ex.describe()["mode"], "local")
    def test_not_ready_without_privilege_or_flag(self):
        ex = make(LOCAL_EXEC_ALLOW_SAME_USER=False); ex.uid = None
        with self.assertRaises(ExecutorError) as e: ex.run("int main(){}")
        self.assertEqual(e.exception.kind, "not_configured")

@unittest.skipUnless(NEED, "g++ not installed")
class AppWithLocalExecutor(unittest.TestCase):
    """The whole Flask app judged by the REAL g++ (no test double)."""
    def test_full_flow(self):
        from tests.helpers import make_app, student, submit, wait_terminal, hdr
        app, _ = make_app(make(), EXECUTOR="local"); s = student(app)
        good = "#include <iostream>\nint main(){ long long a,b; std::cin>>a>>b; std::cout<<a+b; }"
        res = wait_terminal(s, submit(s, 1, good).get_json()["submission_id"], 90); self.assertEqual((res["status"], res["passed_count"], res["total"]), ("evaluated_passed", 4, 4))
        bad = wait_terminal(s, submit(s, 1, '#include <iostream>\nint main(){ std::cout<<"Enter: "; long long a,b; std::cin>>a>>b; std::cout<<a+b; }').get_json()["submission_id"], 90)
        self.assertEqual(bad["status"], "evaluated_failed")
        ce = wait_terminal(s, submit(s, 1, "int main(){ int x = ; }").get_json()["submission_id"], 90); self.assertTrue(ce["compile_output"]); self.assertEqual(ce["status"], "evaluated_failed")
        r = s.post("/api/assignments/1/run", json={"code": good, "stdin": "20 22"}, headers=hdr(s)); self.assertEqual(r.get_json()["stdout"], "42")
        t = __import__("tests.helpers", fromlist=["x"]).teacher(app); page = t.post("/teacher/service", data={"csrf_token": __import__("tests.helpers", fromlist=["x"]).csrf_from(t, "/teacher/service")}).get_data(as_text=True)
        self.assertIn("Working", page); self.assertIn("Local mode", page)
if __name__ == "__main__": unittest.main()

class WindowsSafety(unittest.TestCase):
    def test_module_imports_without_posix_modules(self):
        """Simulates Windows: pwd/resource do not exist. The module must still import and describe itself."""
        import importlib, sys
        saved = {k: sys.modules.get(k) for k in ("pwd", "resource", "local_executor")}
        try:
            sys.modules["pwd"] = None; sys.modules["resource"] = None; sys.modules.pop("local_executor", None)
            mod = importlib.import_module("local_executor"); ex = mod.LocalExecutor(load_config(dict(SECRET_KEY="x", LOCAL_EXEC_ALLOW_SAME_USER=True)))
            self.assertIsNone(mod.pwd); self.assertEqual(ex.describe()["mode"], "local")
        finally:
            for k, v in saved.items():
                if v is None: sys.modules.pop(k, None)
                else: sys.modules[k] = v

class AutoMode(unittest.TestCase):
    def test_auto_picks_local_without_judge0_url_and_judge0_with_url(self):
        from tests.helpers import make_app
        from local_executor import LocalExecutor
        from executor import Judge0Executor
        from app import create_app
        import tempfile
        db = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "a.db")
        a = create_app({"DATABASE_URL": db, "SECRET_KEY": "x", "EXECUTOR": "auto", "JUDGE0_URL": "", "EVAL_SYNC": True})
        self.assertIsInstance(a.extensions["codelab"]["executor"], LocalExecutor)
        db2 = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "b.db")
        b = create_app({"DATABASE_URL": db2, "SECRET_KEY": "x", "EXECUTOR": "auto", "JUDGE0_URL": "http://127.0.0.1:9", "EVAL_SYNC": True})
        self.assertIsInstance(b.extensions["codelab"]["executor"], Judge0Executor)
    def test_default_executor_setting_is_auto(self):
        old = os.environ.pop("EXECUTOR", None)
        try: self.assertEqual(load_config(dict(SECRET_KEY="x"))["EXECUTOR"], "auto")
        finally:
            if old: os.environ["EXECUTOR"] = old
