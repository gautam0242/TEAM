"""Browser acceptance run (Playwright + headless Chromium) against a live local server. Uses the g++-backed Judge0 test double.
Run:  python tests/e2e_browser.py       (needs: pip install playwright && playwright install chromium)"""
import os, subprocess, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
from tests import fake_judge0
RESULTS = []
def check(name, ok, extra=""): RESULTS.append((name, ok)); print(("PASS " if ok else "FAIL ") + name + (" - " + extra if extra and not ok else ""), flush=True)

dbdir = tempfile.mkdtemp(); dbl = fake_judge0.start()
env = dict(os.environ, DATABASE_URL="sqlite:///" + dbdir + "/e2e.db", JUDGE0_URL=dbl.url, JUDGE0_POLL_INTERVAL="0.2", SECRET_KEY="e2e-secret", PORT="5057", APP_ENV="testing")
srv = subprocess.Popen([sys.executable, "-c", "from app import create_app; a=create_app(); a.run(port=5057, threaded=True)"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5); B = "http://127.0.0.1:5057"
GOOD = "#include <iostream>\nusing namespace std;\nint main(){ long long a,b; cin>>a>>b; cout<<a+b; return 0; }"
PROMPTY = "#include <iostream>\nusing namespace std;\nint main(){ long long a,b; cout<<\"Enter: \"; cin>>a>>b; cout<<\"Sum=\"<<a+b; return 0; }"
try:
    with sync_playwright() as p:
        br = p.chromium.launch(); ctx = br.new_context(viewport={"width": 1366, "height": 800}); pg = ctx.new_page()
        pg.goto(B + "/login"); check("login page shows demo note", "Student@123" in pg.content())
        pg.fill("#u", "student01"); pg.fill("#p", "wrong"); pg.click("button.p"); check("wrong password rejected", "Invalid username" in pg.content())
        pg.fill("#u", "student01"); pg.fill("#p", "Student@123"); pg.click("button.p"); pg.wait_for_url("**/student")
        check("student sees assignments grouped by unit", "Unit 1: Basic I/O" in pg.content() and "Unit 4: Arrays" in pg.content())
        pg.goto(B + "/teacher"); check("student blocked from teacher page", "403" in pg.content())
        pg.goto(B + "/assignment/1"); pg.wait_for_selector("#ed"); 
        check("hidden tests not in student page", "2000000000" not in pg.content() and "1000000000 1000000000" not in pg.content())
        eng = pg.inner_text("#engine"); check("editor engine label is honest (Monaco CDN unreachable in sandbox -> textarea)", "basic text editor" in eng, eng)
        pg.fill("#ed", GOOD); pg.fill("#stdin", "20 22"); pg.click("#run"); pg.wait_for_selector("#runout pre", timeout=30000)
        check("Run shows real program output 42", "42" in pg.inner_text("#runout"), pg.inner_text("#runout"))
        pg.fill("#ed", "int main(){ int x = ; }"); pg.click("#run"); pg.locator('#runout:has-text("Compiler diagnostics")').wait_for(timeout=30000)
        check("Run shows real compiler diagnostics", "Compiler diagnostics" in pg.inner_text("#runout"))
        pg.fill("#ed", PROMPTY); pg.click("#submit"); pg.locator('#subout:has-text("tests passed")').wait_for(timeout=60000)
        t = pg.inner_text("#subout"); check("prompt text causes FAILED verdict (output compared strictly)", "failed" in t.lower() and "Hidden test" in t, t)
        check("student sees no hidden values after submit", "2000000000" not in pg.content())
        pg.fill("#ed", GOOD); pg.click("#submit"); pg.locator('#subout:has-text("4/4 tests passed")').wait_for(timeout=60000)
        check("correct code passes 4/4", "4/4 tests passed" in pg.inner_text("#subout"), pg.inner_text("#subout"))
        pg.locator('#history tr').nth(1).wait_for(); check("attempt history shows 2 attempts", pg.inner_text("#history").count("\n") >= 1)
        pg.reload(); pg.wait_for_selector("#history tr td"); check("history persists after refresh", "evaluated_passed" in pg.content() or "passed" in pg.inner_text("#history"))
        check("textarea keeps last submission after refresh", "cout<<a+b" in pg.input_value("#ed"))
        pg.click("#ed"); pg.evaluate("navigator.clipboard && 1"); 
        pg.evaluate("""() => { const e = new Event('paste', {bubbles:true, cancelable:true}); document.getElementById('ed').dispatchEvent(e); }""")
        check("paste deterrent shows notice", pg.is_visible("#notice"))
        pg.goto(B + "/journey"); check("coding journey lists submissions and events", "submission_saved" in pg.content() and "evaluated_passed" in pg.content())
        # keyboard: Tab order reaches Run button
        pg.goto(B + "/assignment/1"); pg.focus("#stdin"); pg.keyboard.press("Tab"); check("keyboard Tab reaches Run button", pg.evaluate("document.activeElement.id") == "run")
        ctx2 = br.new_context(viewport={"width": 1366, "height": 800}); tp = ctx2.new_page(); tp.goto(B + "/login")
        tp.fill("#u", "teacher01"); tp.fill("#p", "Teacher@123"); tp.click("button.p"); tp.wait_for_url("**/teacher")
        check("teacher dashboard shows real counts", "Students attempted" in tp.content() and "evaluated_passed" in tp.content())
        tp.goto(B + "/teacher/submissions"); check("teacher sees student submissions", "Demo Student 01" in tp.content())
        tp.click("text=Open >> nth=0"); check("teacher view shows hidden tests and source", "2000000000" in tp.content() and "cin&gt;&gt;a" in tp.content().replace(">>", "&gt;&gt;"))
        tp.goto(B + "/teacher/assignment/new"); tp.fill("#t", "Browser Made"); tp.fill("#u", "Unit 7"); tp.fill("#ds", "Print hello"); tp.fill("textarea[name=t_expected]", "hello"); tp.click("text=Save assignment"); tp.wait_for_url("**/teacher")
        check("teacher creates an assignment in the browser", "Browser Made" in tp.content())
        tp.goto(B + "/report/2"); pdf = tp.pdf(); check("report renders and prints to PDF", len(pdf) > 3000 and "Lab Submission Report" in tp.content())
        check("report has no hidden expected output", "2000000000" not in tp.content())
        tp.goto(B + "/teacher/service"); tp.click("text=Test connection"); tp.wait_for_selector(".flash, .errbox", timeout=60000); check("service page verifies language and hello-world", "Working" in tp.content(), tp.inner_text("main"))
        dbl.fault = "503"
        pg.goto(B + "/assignment/1"); pg.fill("#ed", GOOD); pg.fill("#stdin", "1 2"); pg.click("#run"); pg.wait_for_selector("#runout .errbox", timeout=60000)
        check("service outage reported honestly on Run", "Nothing was marked wrong" in pg.inner_text("#runout"))
        pg.click("#submit"); pg.locator('#subout:has-text("not a wrong answer")').wait_for(timeout=90000)
        check("service outage on Submit = evaluation error, submission saved", "not a wrong answer" in pg.inner_text("#subout"))
        dbl.fault = None; br.close()
finally:
    srv.terminate()
bad = [n for n, ok in RESULTS if not ok]; print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} browser checks passed"); sys.exit(1 if bad else 0)
