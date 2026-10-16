# CodeLab - Hackathon Demo Day Guide

**Demo accounts (public, demo only):** teacher `teacher01 / Teacher@123` - students `student01 / Student@123`, `student02 / Student@456`.
CodeLab is a Smart Campus **demo**, not an official university system.

## 1. Deploy tonight (about 20 minutes)
1. **GitHub:** repository `codelab` must show these at the TOP level: `app.py`, `Dockerfile`, `local_executor.py`, `render.yaml`, `templates/`, `static/` (no extra folder, no zip inside).
2. **Render:** New -> Web Service -> your `codelab` repo -> Runtime **Docker** -> Instance **Free** -> Environment variables: `APP_ENV=production`, `EXECUTOR=local`, `SECRET_KEY=<40 random characters>` -> Create. First build takes 5-10 minutes.
3. Open your link, log in as `teacher01` -> **Execution service** -> **Test connection**: it must say **Working** and show a g++ version. If not, open Render **Logs** and read the last red lines.
4. Log in as `student01`, open *Fibonacci Series*, paste nothing (paste is blocked) - type the solution from section 4, press **Run** with input `10`, then **Submit**.

## 2. Keep it awake and keep the data (do this the night before)
* Render free sleeps after 15 minutes without visitors (first load then takes about a minute). Make a free **UptimeRobot** account and add an HTTP monitor for `https://YOUR-LINK/health` every 5 minutes. Also open the site 10 minutes before presenting.
* Free Render restarts wipe the SQLite file: assignments you add and submissions made earlier can disappear (the 6 sample assignments come back). For anything you want to keep, create a free **Neon** PostgreSQL database and put its connection string in Render as `DATABASE_URL` (keep `?sslmode=require`), then restart once. Not tested by me with Neon.

## 3. Backup plan: run it on your Windows laptop (no hosting needed)
1. Install a C++ compiler once: PowerShell -> `winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT`, then close and reopen the window and check `g++ --version`.
2. Extract the zip, open the folder and **double-click `START_WINDOWS.bat`**. It creates the environment, installs the packages, creates `.env` and starts the site.
3. Open http://127.0.0.1:5000 and log in. `EXECUTOR=auto` uses your local g++ automatically when no Judge0 URL is set; same-user mode is enabled automatically on Windows.
4. Optional check while the site is running: `python live_check.py` (logs in, runs, submits and waits for the verdict; prints `LIVE CHECK OK`).
Laptop mode runs student code as YOUR user with only a time limit (no memory limit): use it only for yourself. It has worked on your laptop after the Cursor changes; I could not test Windows myself.

## 4. Reference solutions (all verified with real g++ against the seeded tests)
Type these as the student (paste is blocked on purpose). Files are in `tests/solutions/1.cpp ... 6.cpp`.
| # | Assignment | Solution idea |
|---|---|---|
| 1 | Sum of Two Numbers | `long long a,b; cin>>a>>b; cout<<a+b;` |
| 2 | Even or Odd | `if(n%2==0) cout<<"Even"; else cout<<"Odd";` |
| 3 | Factorial | loop with `long long f` |
| 4 | Maximum in Array | start `m=a[0]` (not 0: a hidden test has all negatives) |
| 5 | Reverse a String | print characters from the end |
| 6 | Fibonacci Series | function `printFib(n)`, single spaces |

## 5. Five-minute demo script
1. **Problem (20 s):** students copy lab programs without understanding; CodeLab runs and checks their code and shows teachers how the code was produced.
2. **Student (90 s):** log in as student01 -> *Sum of Two Numbers* -> type a solution that prints `Enter numbers:` -> **Submit** -> **failed**: explain that output is compared exactly. Remove the prompt -> **Run** with `20 22` shows `42` from a real g++ -> **Submit** -> hidden tests pass. Point out: the page never shows hidden tests, only passed/failed.
3. **Compile error (20 s):** delete a `;` -> **Run** -> real compiler message.
4. **Second student (30 s):** student02 submits the same program with renamed variables.
5. **Teacher (90 s):** log in as teacher01 -> dashboard numbers and bars -> **Similarity** page -> flagged pair -> side-by-side view and line differences -> open a submission: hidden test rows, attempt history, activity timeline -> **Report** -> print/save as PDF.
6. **Honest limits (30 s):** the similarity score is a review aid, not proof of cheating; activity logs do not prove authorship; paste blocking is a deterrent; compiling uses g++ in a container with limits (not a full sandbox), so use Judge0 for real exams.

## 6. If something goes wrong on stage
| Symptom | Do this |
|---|---|
| Page loads slowly the first time | Render cold start: wait about a minute, then refresh |
| "Execution service problem" | Teacher -> Execution service -> Test connection and read the message; the student's code is saved and nothing is marked wrong; teacher can press **Re-evaluate** later |
| Submission stays "waiting for evaluation" | The free server is busy compiling another program; wait 30 seconds |
| Data vanished | Free-tier restart (see section 2); log in again, the sample assignments are back |
| Everything is down | Switch to the laptop backup (section 3) |
