import unittest
from evaluation import normalize, ALLOWED, set_status
import similarity as S
from security import RateLimiter, LoginThrottle

class Normalize(unittest.TestCase):
    def test_lenient(self):
        self.assertEqual(normalize("7\r\n"), "7"); self.assertEqual(normalize("a  \nb \n\n\n"), "a\nb"); self.assertEqual(normalize(""), ""); self.assertEqual(normalize(None), "")
        self.assertEqual(normalize("a  b"), "a  b")                        # internal spacing preserved
        self.assertNotEqual(normalize("1 2"), normalize("1  2")); self.assertNotEqual(normalize("Yes"), normalize("yes"))
        self.assertNotEqual(normalize(""), normalize("0"))                  # empty output is NOT silently equal to anything
    def test_exact(self):
        self.assertEqual(normalize("7\n", "exact"), "7"); self.assertNotEqual(normalize("7 \n", "exact"), "7"); self.assertEqual(normalize("a\r\nb", "exact"), "a\nb")

class Similarity(unittest.TestCase):
    BASE = """#include <iostream>
using namespace std;
// reads two numbers
int main(){ int a,b; cin>>a>>b; cout<<"sum // is: "<<a+b<<endl; int total=0; for(int i=0;i<a;i++){ total+=i; } cout<<total; return 0; }"""
    def test_tokenizer_strings_and_comments(self):
        t = [x for _, x in S.tokenize('int a=1; // c1\nint b=2; /* c2 */ cout<<"x//y /* z */"; char c=\'"\'; int d=3;')]
        self.assertIn('"x//y /* z */"', t); self.assertIn("d", t); self.assertNotIn("c1", t); self.assertNotIn("c2", t)
        self.assertEqual(t.count("int"), 3)                                 # a line comment must not swallow the rest of the file
        self.assertEqual(len(S.tokenize("// only a comment")), 0); self.assertEqual(len(S.tokenize('/* unterminated')), 0)
    def test_identical_and_renamed(self):
        r = S.compare(self.BASE, self.BASE, 10); self.assertEqual(r["token_score"], 1.0)
        renamed = self.BASE.replace("a", "x").replace("b", "y").replace("total", "acc").replace("// reads two numbers", "// different comment")
        r = S.compare(self.BASE, renamed, 10); self.assertGreater(r["structure_score"], 0.9); self.assertLess(r["token_score"], r["structure_score"])
        self.assertTrue(S.flagged(r, 0.85))
    def test_unrelated_low_short_and_template_skipped(self):
        other = "#include <vector>\nint main(){ std::vector<int> v; for(int i=0;i<10;i++) v.push_back(i*i); long s=0; for(auto x:v) s+=x; return s>100; }"
        self.assertLess(S.compare(self.BASE, other, 10)["structure_score"], 0.6)
        self.assertFalse(S.compare("int main(){}", "int main(){}", 25)["comparable"])
        tpl = "#include <iostream>\nusing namespace std;\nint main(){ return 0; }"
        r = S.compare(tpl, self.BASE, 3, template=tpl); self.assertFalse(r["comparable"]); self.assertFalse(S.flagged(r, 0.0))
    def test_comment_only_difference_is_identical(self):
        self.assertEqual(S.compare(self.BASE, self.BASE.replace("// reads two numbers", "/* hello */"), 10)["token_score"], 1.0)

class StateMachine(unittest.TestCase):
    def test_table(self):
        self.assertNotIn("evaluated_passed", ALLOWED["submitted"]); self.assertIn("evaluating", ALLOWED["evaluation_pending"])
        self.assertEqual(ALLOWED["evaluating"], {"evaluated_passed", "evaluated_failed", "evaluation_error"})
    def test_set_status_rejects_illegal(self):
        import tempfile, os
        from db import DB, now
        d = DB("sqlite:///" + os.path.join(tempfile.mkdtemp(), "x.db")); d.create_all()
        with d.session() as s:
            s.insert("users", username="u", name="U", role="student", pw_hash="x", created_at=now())
            s.insert("assignments", title="t", unit="u", description="d", starter="s", created_at=now())
            sid = s.insert("submissions", user_id=1, assignment_id=1, code="c", attempt=1, status="submitted", client_token="tok12345", created_at=now())
            self.assertFalse(set_status(s, sid, "evaluated_passed")); self.assertTrue(set_status(s, sid, "evaluation_pending")); self.assertTrue(set_status(s, sid, "evaluating"))
            self.assertFalse(set_status(s, sid, "evaluating")); self.assertTrue(set_status(s, sid, "evaluated_failed"))

class Limits(unittest.TestCase):
    def test_rate_limiter_window(self):
        t = [0.0]; rl = RateLimiter(2, 10, clock=lambda: t[0])
        self.assertTrue(rl.allow("k")); self.assertTrue(rl.allow("k")); self.assertFalse(rl.allow("k")); self.assertTrue(rl.allow("other"))
        t[0] = 11; self.assertTrue(rl.allow("k"))
    def test_login_throttle_expires(self):
        t = [0.0]; lt = LoginThrottle(3, 60, clock=lambda: t[0])
        for _ in range(3): lt.fail("k")
        self.assertTrue(lt.blocked("k")); t[0] = 61; self.assertFalse(lt.blocked("k"))

if __name__ == "__main__": unittest.main()
