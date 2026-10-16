@echo off
cd /d "%~dp0"
where py >nul 2>&1 && set PY=py -3 || set PY=python
if not exist venv (
  echo Creating virtual environment...
  %PY% -m venv venv
)
call venv\Scripts\activate.bat
call venv\Scripts\python.exe -m pip install -q -r requirements.txt
if not exist .env copy /Y .env.example .env >nul
where g++ >nul 2>&1 || echo WARNING: g++ was not found. Install it with: winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT  ^(then reopen this window^)
call venv\Scripts\python.exe init_db.py
echo.
echo ====================================================
echo  CodeLab is ready!
echo  Open http://127.0.0.1:5000 in your web browser
echo  Demo logins:
echo    Student: student01 / Student@123
echo    Teacher: teacher01 / Teacher@123
echo ====================================================
echo.
call venv\Scripts\python.exe app.py
pause
