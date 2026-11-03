@echo off
rem Same promise as symbiont-hook.sh, for hosts that run hooks through cmd.exe (Muse Code on Windows):
rem print one line when symbiont is missing, and always exit 0 so the agent is never blocked.
rem Muse Code sets CLAUDE_PLUGIN_ROOT and runs the hook command with cmd.exe, which has no sh [measured:
rem Muse 1.4.14 on Windows 11]; hooks.json tries sh first and falls back to this file.
rem Muse Code hands hooks HOME but not USERPROFILE, and Python finds the home directory from USERPROFILE.
setlocal
if not defined USERPROFILE set "USERPROFILE=%HOME%"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
if exist "%USERPROFILE%\.symbiont\hook-trace.on" >>"%USERPROFILE%\.symbiont\hook-trace.jsonl" echo {"stage":"wrapper","event":"%~1","ts":"%DATE% %TIME%"}
where symbiont-hook >nul 2>&1
if errorlevel 1 (
  if "%~1"=="SessionStart" echo {"systemMessage":"symbiont is not installed, so it is off. Install it with: uv tool install git+https://github.com/smalls257/ai-symbiont"}
  exit /b 0
)
rem call: without it a .cmd shim would end this script before the exit below.
call symbiont-hook %*
exit /b 0
