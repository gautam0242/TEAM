"""Checks a RUNNING CodeLab server end to end (login, Run, Submit, evaluation) with real compiled C++.
Usage:  python live_check.py [http://127.0.0.1:5000]"""
import json, re, sys, time, urllib.parse, urllib.request, http.cookiejar
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000").rstrip("/")
CODE = "#include <iostream>\nint main(){ long long a,b; std::cin>>a>>b; std::cout<<a+b; }\n"
cj = http.cookiejar.CookieJar(); opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def get(path):
    r = opener.open(BASE + path, timeout=120); return r.status, r.read().decode()
def post_form(path, data):
    r = opener.open(urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=120); return r.status, r.read().decode()
def post_json(path, payload, csrf):
    r = opener.open(urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "X-CSRF-Token": csrf}), timeout=300); return r.status, r.read().decode()
st, health = get("/health"); print("HEALTH", st, health)
assert json.loads(health)["executor_configured"] is True, "executor not configured"
st, html = get("/login"); csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
post_form("/login", {"username": "student01", "password": "Student@123", "csrf_token": csrf})
st, page = get("/student"); assert st == 200 and "Sum of Two" in page
csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
st, ws = get("/assignment/1"); assert st == 200 and "Sample cases" in ws
st, out = post_json("/api/assignments/1/run", {"code": CODE, "stdin": "20 22"}, csrf); print("RUN", st, out)
assert json.loads(out).get("stdout") == "42", out
st, out = post_json("/api/assignments/1/submit", {"code": CODE, "client_token": "livecheck" + str(int(time.time()))}, csrf); print("SUBMIT", st, out)
sid = json.loads(out)["submission_id"]; final = None
for _ in range(150):
    st, body = get(f"/api/submissions/{sid}"); d = json.loads(body); print("POLL", d["status"], d.get("passed_count"), d.get("total"))
    if d["status"] in ("evaluated_passed", "evaluated_failed", "evaluation_error"): final = d; break
    time.sleep(0.8)
assert final and final["status"] == "evaluated_passed" and final["passed_count"] == final["total"], final
print("LIVE CHECK OK")
