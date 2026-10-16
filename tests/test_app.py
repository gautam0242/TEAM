import json, threading, time, unittest, os
from tests.helpers import *
import evaluation

GOOD = "int main(){ /* SUM */ }"

class AuthTests(unittest.TestCase):
    def setUp(self): self.app, _ = make_app()
    def test_login_logout_and_wrong_password(self):
        c = self.app.test_client()
        self.assertEqual(login(c, "student01", "wrong").status_code, 200)       # stays on login page
        self.assertEqual(c.get("/student").status_code, 302)                     # not logged in -> redirect
        r = login(c, "student01", "Student@123"); self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get("/student").status_code, 200)
        c.post("/logout", data={"csrf_token": csrf_from(c, "/student")}); self.assertEqual(c.get("/student").status_code, 302)
    def test_csrf_rejected(self):
        c = student(self.app)
        self.assertEqual(c.post("/api/assignments/1/run", json={"code": "x"}).status_code, 400)
        self.assertEqual(c.post("/logout", data={}).status_code, 400)
        self.assertEqual(self.app.test_client().post("/login", data={"username": "a", "password": "b"}).status_code, 400)
    def test_login_throttle(self):
        c = self.app.test_client()
        for _ in range(5): login(c, "student01", "bad")
        self.assertEqual(login(c, "student01", "Student@123").status_code, 429)  # locked even with the right password
        self.assertEqual(login(self.app.test_client(), "teacher01", "Teacher@123").status_code, 302)  # other account unaffected
    def test_role_enforcement(self):
        s, t = student(self.app), teacher(self.app)
        for path in ("/teacher", "/teacher/submissions", "/teacher/assignment/new", "/teacher/service", "/teacher/similarity/1", "/teacher/submission/1"):
            self.assertEqual(s.get(path).status_code, 403, path)
        self.assertEqual(s.post("/teacher/assignment/1/delete", headers=hdr(s)).status_code, 403)
        self.assertEqual(t.get("/student").status_code, 403)
        self.assertEqual(t.post("/api/assignments/1/run", json={"code": "x"}, headers=hdr(t)).status_code, 403)
        self.assertEqual(t.get("/teacher").status_code, 200)
    def test_health_and_headers(self):
        c = self.app.test_client(); r = c.get("/health"); self.assertEqual(r.get_json()["status"], "ok")
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"]); self.assertEqual(r.headers["X-Frame-Options"], "DENY")
    def test_production_requires_secret_and_secure_cookie(self):
        old = {k: os.environ.pop(k, None) for k in ("SECRET_KEY",)}
        try:
            os.environ["APP_ENV"] = "production"
            from config import load_config
            with self.assertRaises(RuntimeError): load_config()
            os.environ["SECRET_KEY"] = "x" * 40
            self.assertEqual(load_config()["APP_ENV"], "production")
            app, _ = make_app(APP_ENV="production", SECRET_KEY="y" * 40); self.assertTrue(app.config["SESSION_COOKIE_SECURE"])
        finally:
            os.environ.pop("APP_ENV", None); os.environ.pop("SECRET_KEY", None)
            for k, v in old.items():
                if v: os.environ[k] = v

class HiddenTests(unittest.TestCase):
    def setUp(self): self.app, _ = make_app()
    def test_hidden_values_never_reach_student(self):
        s = student(self.app); r = submit(s, 1, GOOD); sid = r.get_json()["submission_id"]
        res = wait_terminal(s, sid); self.assertEqual(res["status"], "evaluated_passed")
        blobs = [s.get("/assignment/1").get_data(as_text=True), json.dumps(res), s.get(f"/report/{sid}").get_data(as_text=True),
                 s.get("/student").get_data(as_text=True), s.get("/journey").get_data(as_text=True), s.get("/api/assignments/1/submissions").get_data(as_text=True)]
        for b in blobs:
            self.assertNotIn(HIDDEN_INPUT, b); self.assertNotIn(HIDDEN_EXPECTED, b)
        self.assertEqual(sum(1 for t in res["results"] if t["hidden"]), 2)
        for t in res["results"]:
            if t["hidden"]: self.assertEqual(set(t), {"position", "hidden", "status"})
    def test_hidden_failure_details_not_leaked(self):
        s = student(self.app); sid = submit(s, 1, "WRONG").get_json()["submission_id"]; res = wait_terminal(s, sid)
        self.assertEqual(res["status"], "evaluated_failed"); self.assertNotIn(HIDDEN_EXPECTED, json.dumps(res))
        self.assertNotIn(HIDDEN_EXPECTED, s.get(f"/report/{sid}").get_data(as_text=True))
    def test_teacher_can_see_hidden(self):
        s = student(self.app); sid = submit(s, 1, GOOD).get_json()["submission_id"]
        t = teacher(self.app); self.assertIn(HIDDEN_EXPECTED, t.get(f"/teacher/submission/{sid}").get_data(as_text=True))
        self.assertIn(HIDDEN_EXPECTED, t.get("/teacher/assignment/1/edit").get_data(as_text=True))
        self.assertNotIn(HIDDEN_EXPECTED, t.get(f"/report/{sid}").get_data(as_text=True))   # report never prints hidden values
    def test_error_messages_do_not_leak(self):
        s = student(self.app); sid = submit(s, 1, "RUNTIME_FAIL").get_json()["submission_id"]
        self.assertNotIn(HIDDEN_EXPECTED, json.dumps(wait_terminal(s, sid)))

class SubmissionFlow(unittest.TestCase):
    def setUp(self): self.ex = ScriptedExecutor(); self.app, self.dir = make_app(self.ex)
    def test_pass_and_states_and_events(self):
        s = student(self.app); r = submit(s, 1, GOOD); self.assertEqual(r.status_code, 202)
        res = wait_terminal(s, r.get_json()["submission_id"])
        self.assertEqual((res["status"], res["passed_count"], res["total"]), ("evaluated_passed", 4, 4))
        with self.app.extensions["codelab"]["db"].session() as q: types = [e["type"] for e in q.q("SELECT type FROM events ORDER BY id")]
        for t in ("submission_saved", "evaluation_completed"): self.assertIn(t, types)
    def test_wrong_answer_is_failed_not_error(self):
        s = student(self.app); res = wait_terminal(s, submit(s, 1, "WRONG").get_json()["submission_id"])
        self.assertEqual(res["status"], "evaluated_failed"); self.assertLess(res["passed_count"], res["total"])
    def test_compile_error_is_failed_with_output(self):
        s = student(self.app); res = wait_terminal(s, submit(s, 1, "COMPILE_FAIL").get_json()["submission_id"])
        self.assertEqual(res["status"], "evaluated_failed"); self.assertIn("expected expression", res["compile_output"])
    def test_runtime_error_per_test(self):
        s = student(self.app); res = wait_terminal(s, submit(s, 1, "RUNTIME_FAIL").get_json()["submission_id"])
        self.assertEqual(res["status"], "evaluated_failed"); self.assertTrue(all(t["status"] == "error" for t in res["results"]))
    def test_service_down_is_error_not_wrong_answer(self):
        s = student(self.app); res = wait_terminal(s, submit(s, 1, "SERVICE_DOWN").get_json()["submission_id"])
        self.assertEqual(res["status"], "evaluation_error"); self.assertNotEqual(res["status"], "evaluated_failed")
        self.assertIn("incomplete", res["error_message"].lower())
        self.assertEqual(len(s.get("/api/assignments/1/submissions").get_json()["submissions"]), 1)   # submission preserved
    def test_partial_failure_never_marked_passed(self):
        self.ex.fail_after = 2; s = student(self.app); res = wait_terminal(s, submit(s, 1, GOOD).get_json()["submission_id"])
        self.assertEqual(res["status"], "evaluation_error"); self.assertEqual(len(res["results"]), 2); self.assertEqual(res["passed_count"], 2)
    def test_reevaluate_after_service_recovers(self):
        self.ex.fail_after = 1; s = student(self.app); sid = submit(s, 1, GOOD).get_json()["submission_id"]
        self.assertEqual(wait_terminal(s, sid)["status"], "evaluation_error")
        self.ex.fail_after = None; t = teacher(self.app)
        t.post(f"/teacher/submission/{sid}/reevaluate", data={"csrf_token": csrf_from(t, "/teacher")})
        res = wait_terminal(s, sid); self.assertEqual((res["status"], res["passed_count"]), ("evaluated_passed", 4))
    def test_duplicate_click_same_token(self):
        s = student(self.app); a = submit(s, 1, GOOD, token="abcdefgh12345").get_json(); b = submit(s, 1, GOOD, token="abcdefgh12345").get_json()
        self.assertEqual(a["submission_id"], b["submission_id"]); self.assertTrue(b.get("duplicate"))
        self.assertEqual(len(s.get("/api/assignments/1/submissions").get_json()["submissions"]), 1)
    def test_validation(self):
        s = student(self.app)
        self.assertEqual(s.post("/api/assignments/1/submit", json={"code": "", "client_token": "abcdefgh1"}, headers=hdr(s)).status_code, 400)
        self.assertEqual(s.post("/api/assignments/1/submit", json={"code": "x", "client_token": "!!"}, headers=hdr(s)).status_code, 400)
        self.assertEqual(submit(s, 1, "x" * 60000).status_code, 413)
        self.assertEqual(s.post("/api/assignments/1/run", json={"code": "x", "stdin": "y" * 20000}, headers=hdr(s)).status_code, 413)
        self.assertEqual(submit(s, 999, "x").status_code, 404)
    def test_ownership(self):
        s1, s2 = student(self.app), student(self.app, "student02")
        sid = submit(s1, 1, GOOD).get_json()["submission_id"]; wait_terminal(s1, sid)
        self.assertEqual(s2.get(f"/api/submissions/{sid}").status_code, 404); self.assertEqual(s2.get(f"/report/{sid}").status_code, 404)
        self.assertEqual(s1.get(f"/report/{sid}").status_code, 200)
        self.assertEqual(s2.get("/api/assignments/1/submissions").get_json()["submissions"], [])
    def test_run_endpoint_and_service_error_creates_no_submission(self):
        s = student(self.app); r = s.post("/api/assignments/1/run", json={"code": GOOD, "stdin": "3 4"}, headers=hdr(s))
        self.assertEqual((r.status_code, r.get_json()["stdout"].strip()), (200, "7"))
        r = s.post("/api/assignments/1/run", json={"code": "SERVICE_DOWN", "stdin": ""}, headers=hdr(s))
        self.assertEqual(r.status_code, 503); self.assertEqual(r.get_json()["kind"], "network")
        self.assertEqual(s.get("/api/assignments/1/submissions").get_json()["submissions"], [])
    def test_rate_limits(self):
        app, _ = make_app(ScriptedExecutor(), RATE_SUBMIT_PER_MIN=2, RATE_RUN_PER_MIN=2); s = student(app)
        codes = [s.post("/api/assignments/1/run", json={"code": GOOD}, headers=hdr(s)).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        r = [submit(s, 1, GOOD).status_code for _ in range(3)]; self.assertEqual(r[2], 429)

class Concurrency(unittest.TestCase):
    def test_second_submission_blocked_while_evaluating_then_allowed(self):
        ex = ScriptedExecutor(); ex.gate = threading.Event()
        app, _ = make_app(ex, EVAL_SYNC=False); s = student(app)
        a = submit(s, 1, GOOD); self.assertEqual(a.status_code, 202)
        b = submit(s, 1, GOOD); self.assertEqual(b.status_code, 409)         # atomic guard (partial unique index)
        ex.gate.set(); self.assertEqual(wait_terminal(s, a.get_json()["submission_id"])["status"], "evaluated_passed")
        c = submit(s, 1, GOOD); self.assertEqual(c.status_code, 202); wait_terminal(s, c.get_json()["submission_id"])
    def test_stale_evaluations_reaped(self):
        ex = ScriptedExecutor(); ex.gate = threading.Event()
        app, _ = make_app(ex, EVAL_SYNC=False, STALE_EVAL_MINUTES=0); s = student(app)
        a = submit(s, 1, GOOD); time.sleep(1.1)
        b = submit(s, 1, GOOD); self.assertEqual(b.status_code, 202)           # stale one was reaped, not blocking forever
        ex.gate.set(); wait_terminal(s, b.get_json()["submission_id"])

class Persistence(unittest.TestCase):
    def test_survives_restart_and_recovers_pending(self):
        ex = ScriptedExecutor(); app, d = make_app(ex); s = student(app); sid = submit(s, 1, GOOD).get_json()["submission_id"]; wait_terminal(s, sid)
        url = "sqlite:///" + os.path.join(d, "t.db")
        app2 = create_app({"DATABASE_URL": url, "EVAL_SYNC": True, "SECRET_KEY": "test-secret", "APP_ENV": "testing"}, executor=ScriptedExecutor())
        s2 = student(app2); self.assertEqual(s2.get(f"/api/submissions/{sid}").get_json()["status"], "evaluated_passed")
        self.assertEqual(len(s2.get("/api/assignments/1/submissions").get_json()["submissions"]), 1)
        # simulate a crash mid-evaluation, then restart recovery
        db = app2.extensions["codelab"]["db"]
        with db.session() as q: q.exec("UPDATE submissions SET status='evaluating' WHERE id=?", (sid,))
        app2.recover_pending(); self.assertEqual(s2.get(f"/api/submissions/{sid}").get_json()["status"], "evaluated_passed")
    def test_init_does_not_erase_data(self):
        app, d = make_app(); s = student(app); submit(s, 1, GOOD)
        import init_db; from db import DB
        db = DB("sqlite:///" + os.path.join(d, "t.db")); db.create_all(); self.assertFalse(init_db.seed(db))
        with db.session() as q: self.assertEqual(q.one("SELECT COUNT(*) AS n FROM submissions")["n"], 1)

class TeacherTests(unittest.TestCase):
    def setUp(self): self.app, _ = make_app(); self.t = teacher(self.app)
    def form(self, **o):
        f = {"csrf_token": csrf_from(self.t, "/teacher"), "title": "New Task", "unit": "Unit 9", "description": "desc", "deadline": "2026-12-01", "time_limit": "2",
             "compare_mode": "lenient", "t_input": ["1 2", "5 5"], "t_expected": ["3", "10"], "t_hidden": ["0", "1"]}; f.update(o); return f
    def test_create_edit_validate_delete_archive(self):
        r = self.t.post("/teacher/assignment/new", data=self.form(), follow_redirects=True); self.assertIn(b"New Task", r.data)
        db = self.app.extensions["codelab"]["db"]
        with db.session() as q: aid = q.one("SELECT id FROM assignments WHERE title='New Task'")["id"]; self.assertEqual(q.one("SELECT COUNT(*) n FROM tests WHERE assignment_id=?", (aid,))["n"], 2)
        bad = self.t.post("/teacher/assignment/new", data=self.form(title=""), follow_redirects=True); self.assertIn(b"Title is required", bad.data)
        bad = self.t.post("/teacher/assignment/new", data=self.form(t_input=[], t_expected=[], t_hidden=[]), follow_redirects=True); self.assertIn(b"at least one test", bad.data)
        self.t.post(f"/teacher/assignment/{aid}/edit", data=self.form(title="Renamed"), follow_redirects=True)
        with db.session() as q: self.assertEqual(q.one("SELECT title FROM assignments WHERE id=?", (aid,))["title"], "Renamed")
        s = student(self.app); self.assertIn(b"Renamed", s.get("/student").data)
        self.t.post(f"/teacher/assignment/{aid}/delete", data={"csrf_token": csrf_from(self.t, "/teacher")})      # no submissions -> deleted
        with db.session() as q: self.assertIsNone(q.one("SELECT id FROM assignments WHERE id=?", (aid,)))
    def test_delete_with_submissions_archives(self):
        s = student(self.app); sid = submit(s, 1, GOOD).get_json()["submission_id"]; wait_terminal(s, sid)
        self.t.post("/teacher/assignment/1/delete", data={"csrf_token": csrf_from(self.t, "/teacher")})
        self.assertNotIn(b'href="/assignment/1"', s.get("/student").data); self.assertEqual(s.get("/assignment/1").status_code, 404)
        self.assertEqual(self.t.get(f"/teacher/submission/{sid}").status_code, 200)   # evidence kept
        self.t.post("/teacher/assignment/1/restore", data={"csrf_token": csrf_from(self.t, "/teacher")}); self.assertIn(b'href="/assignment/1"', s.get("/student").data)
    def test_review_filters_dashboard_report_and_similarity(self):
        a, b = student(self.app), student(self.app, "student02")
        code = "#include <iostream>\nusing namespace std;\nint main(){ long long a,b; cin>>a>>b; long long s=a+b; cout<<s<<endl; return 0; } // SUM"
        ra = submit(a, 1, code).get_json()["submission_id"]; rb = submit(b, 1, code.replace("a,b", "x,y").replace(">>a>>b", ">>x>>y").replace("a+b", "x+y").replace(" s=", " t=").replace("<<s", "<<t")).get_json()["submission_id"]
        wait_terminal(a, ra); wait_terminal(b, rb)
        r = self.t.get(f"/teacher/submission/{ra}").get_data(as_text=True); self.assertIn("flagged for review", r); self.assertIn("not proof of copying", r)
        with self.app.extensions["codelab"]["db"].session() as q: self.assertIn("submission_reviewed", [e["type"] for e in q.q("SELECT type FROM events")])
        self.assertIn(b"review", self.t.get("/teacher/similarity/1").data); self.assertEqual(self.t.get(f"/teacher/compare/{ra}/{rb}").status_code, 200)
        self.assertEqual(self.t.get("/teacher/compare/1/999").status_code, 404)
        f = self.t.get("/teacher/submissions?assignment=1&status=evaluated_passed").get_data(as_text=True); self.assertIn("Demo Student 01", f)
        self.assertIn("No submissions match", self.t.get("/teacher/submissions?status=evaluation_error").get_data(as_text=True))
        d = self.t.get("/teacher").get_data(as_text=True); self.assertIn("Students attempted / passed", d)
        self.assertEqual(self.t.get(f"/report/{ra}").status_code, 200)
    def test_no_viva_anywhere(self):
        for p in ("/teacher", "/student", "/teacher/submissions"):
            c = self.t if p.startswith("/teacher") else student(self.app)
            self.assertNotIn("viva", c.get(p).get_data(as_text=True).lower())
        self.assertEqual(self.t.post("/teacher/viva/1", data={"csrf_token": csrf_from(self.t, "/teacher")}).status_code, 404)
        with self.app.extensions["codelab"]["db"].session() as q: self.assertEqual(q.q("SELECT name FROM sqlite_master WHERE name LIKE '%viva%'"), [])

if __name__ == "__main__": unittest.main()
