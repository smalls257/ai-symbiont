@echo off
rem Same promise as symbiont-hook.sh, for hosts that run hooks through cmd.exe (Muse Code on Windows):
rem print one line when symbiont is missing, and always exit 0 so the agent is never blocked.
rem Muse Code sets CLAUDE_PLUGIN_ROOT and runs the hook command with cmd.exe, which has no sh [measured:
rem Muse 1.4.14 on Windows 11]; hooks.json tries sh first and falls back to this file.
setlocal
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
if exist "%USERPROFILE%\.symbiont\hook-trace.on" >>"%USERPROFILE%\.symbiont\hook-trace.jsonl" echo {"stage":"wrapper","event":"%~1","ts":"%DATE% %TIME%"}
where symbiont-hook >nul 2>&1
if errorlevel 1 (
  if "%~1"=="SessionStart" echo {"systemMessage":"symbiont is not installed, so it is off. Install it with: uv tool install git+https://github.com/smalls257/ai-symbiont"}
  exit /b 0
)
symbiont-hook %*
exit /b 0
