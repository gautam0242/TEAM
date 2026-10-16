"""Final-version browser check: headless Chromium -> live server with EXECUTOR=local -> REAL g++ (no test double)."""
import os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
R = []
def check(n, ok, x=""): R.append(ok); print(("PASS " if ok else "FAIL ") + n + ("" if ok else " - " + str(x)), flush=True)
env = dict(os.environ, DATABASE_URL="sqlite:///" + tempfile.mkdtemp() + "/f.db", EXECUTOR="local", SECRET_KEY="e2e", APP_ENV="testing", PORT="5058")
srv = subprocess.Popen([sys.executable, "-c", "from app import create_app; create_app().run(port=5058, threaded=True)"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5); B = "http://127.0.0.1:5058"
sol = open(os.path.join(os.path.dirname(__file__), "solutions", "6.cpp")).read()
try:
    with sync_playwright() as p:
        br = p.chromium.launch(); pg = br.new_context(viewport={"width": 1366, "height": 800}).new_page()
        pg.goto(B + "/login"); pg.fill("#u", "student01"); pg.fill("#p", "Student@123"); pg.click("button.p"); pg.wait_for_url("**/student")
        check("6 assignments across 6 units", pg.content().count('href="/assignment/') == 6)
        pg.goto(B + "/assignment/6"); pg.wait_for_selector("#ed")
        pg.fill("#ed", "int main(){ int x = ; }"); pg.click("#run"); pg.locator('#runout:has-text("Compiler diagnostics")').wait_for(timeout=60000)
        check("real g++ compile error shown", "error" in pg.inner_text("#runout").lower())
        pg.fill("#ed", sol); pg.fill("#stdin", "10"); pg.click("#run"); pg.locator('#runout:has-text("Program output")').wait_for(timeout=60000)
        check("Run prints Fibonacci from real program", "0 1 1 2 3 5 8 13 21 34" in pg.inner_text("#runout"), pg.inner_text("#runout"))
        pg.click("#submit"); pg.locator('#subout:has-text("tests passed")').wait_for(timeout=90000)
        check("Submit judged by real g++: 4/4 passed", "4/4 tests passed" in pg.inner_text("#subout"), pg.inner_text("#subout"))
        check("hidden values not in student page", "0 1 1 2 3 5 8 13 21 34" not in pg.locator("section").first.inner_text())
        t = br.new_context(viewport={"width": 1366, "height": 800}).new_page(); t.goto(B + "/login"); t.fill("#u", "teacher01"); t.fill("#p", "Teacher@123"); t.click("button.p"); t.wait_for_url("**/teacher")
        t.goto(B + "/teacher/service"); t.click("text=Test connection"); t.wait_for_selector(".flash, .errbox", timeout=60000)
        check("teacher 'Test connection' says Working with g++ version", "Working" in t.content() and "g++" in t.content(), t.inner_text("main"))
        t.goto(B + "/teacher/submissions"); t.click("text=Open >> nth=0"); check("teacher sees hidden test rows", "0 1 1 2 3 5 8 13 21 34" in t.content())
        t.goto(B + "/report/1"); check("report prints to PDF", len(t.pdf()) > 3000)
        br.close()
finally: srv.terminate()
print(f"\n{sum(R)}/{len(R)} browser checks passed"); sys.exit(0 if all(R) else 1)
