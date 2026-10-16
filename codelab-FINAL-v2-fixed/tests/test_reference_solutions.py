"""Every seeded assignment is solved by a reference C++ program and judged by the REAL g++ through the whole app.
Also proves the typical mistakes (printing prompts, wrong answer, compile error) are rejected."""
import os, unittest, shutil
from tests.helpers import make_app, student, submit, wait_terminal
from tests.test_local_executor import make
HERE = os.path.dirname(__file__)
def src(i):
    with open(os.path.join(HERE, "solutions", f"{i}.cpp"), "r", encoding="utf-8") as f:
        return f.read()

@unittest.skipUnless(shutil.which("g++"), "g++ not installed")
class Reference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, _ = make_app(make(), EXECUTOR="local", RATE_SUBMIT_PER_MIN=100); cls.s = student(cls.app)
    def judge(self, aid, code):
        return wait_terminal(self.s, submit(self.s, aid, code).get_json()["submission_id"], 120)
    def test_all_six_reference_solutions_pass(self):
        for i in range(1, 7):
            with self.subTest(assignment=i):
                r = self.judge(i, src(i)); self.assertEqual(r["status"], "evaluated_passed", r); self.assertEqual(r["passed_count"], r["total"])
    def test_typical_mistakes_fail(self):
        prompt = src(1).replace("cin >> a >> b;", 'cout << "Enter numbers: "; cin >> a >> b;'); self.assertEqual(self.judge(1, prompt)["status"], "evaluated_failed")
        label = src(2).replace('cout << "Even"', 'cout << "Number is Even"'); self.assertEqual(self.judge(2, label)["status"], "evaluated_failed")
        wrong = src(3).replace("long long f", "int f"); res = self.judge(3, wrong); self.assertEqual(res["status"], "evaluated_passed")  # 12! fits in int: this is still correct
        off = src(4).replace("int m = a[0];", "int m = 0;"); self.assertEqual(self.judge(4, off)["status"], "evaluated_failed")   # all-negative hidden test catches it
        self.assertEqual(self.judge(5, src(5).replace("s.size() - 1", "s.size() - 2"))["status"], "evaluated_failed")
        self.assertEqual(self.judge(6, src(6).replace('cout << " ";', 'cout << ",";'))["status"], "evaluated_failed")
        ce = self.judge(1, src(1).replace("cout << a + b;", "cout << a + b")); self.assertEqual(ce["status"], "evaluated_failed"); self.assertTrue(ce["compile_output"])
if __name__ == "__main__": unittest.main()
